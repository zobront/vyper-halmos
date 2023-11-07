import os
import subprocess
import json
import helpers
import re

CONTRACTS_DIR = "contracts/"
TESTS_DIR = "test/test/"
standard_kwargs = {"shell": True, "stdout": subprocess.PIPE, "check": True, "text": True}

def wrap_for_type(type, idx):
    # value types: bool, int, uint, decirmal, address, bytes, Bytes[X], String[X], enum
    # reference types: fixed lists (uint256[3]), multidimensional, DynArray[type, len], Struct

    pattern = r'\[([^\]]*)\]'
    lens = re.findall(pattern, type)
    if len(lens) > 2:
        raise TypeError("triple nested")
    if len(lens) > 0:
        base_type = (re.search(r'^(.*?)\[', type)).group(1)
        wrapped = wrap_for_type(base_type, idx)

        # if dynamic, just abi encode it
        if lens[0] == "":
            return f"abi.encode({wrapped})"

        # if static, upper bits are cleaned, go back to uint256 for encodePacked
        # @todo: static array of strings will pack the normally encoded strings?
        length = int(lens[0]) if len(lens) == 1 else int(lens[0]) * int(lens[1])
        if length > 4: raise TypeError("arg array with too many elements")
        return f"abi.encodePacked({', '.join([wrapped for i in range(length)])})"

    # for ints, wrap in same size uint: intX(uintX(arg))
    if type.startswith("int"):
        return f"int256({type}(u{type}(args[{idx}])))"

    # for uints, wrap directly: uintX(arg)
    elif type.startswith("uint"):
        return f"uint256({type}(args[{idx}]))"

    # for decimals, wrap into uint168: uint168(arg)
    elif type.startswith("decimal"):
        return f"uint256(uint168(args[{idx}]))"

    # String[X] / Bytes[X] are just abi encoded
    elif type == "string":
        return '"TestString"'

    elif type == "bytes":
        return 'b"\x00\x01\x02\x03"'

    # for bool, return whether the value is > 0
    elif type.startswith("bool"):
        return f"uint256(args[{idx}] > 0 ? 1 : 0)"

    # for address
    elif type == "address":
        return f"uint256(uint160(args[{idx}]))"

    # if it's hardcoded bytes type
    elif type.startswith("bytes"):
        if type == "bytes32":
            return f"bytes32(args[{idx}])"
        return f"bytes32({type}(bytes32(args[{idx}])))"

    # no solution for Struct or Enum yet
    else:
        raise TypeError("enum or struct arg")


for file in os.listdir(CONTRACTS_DIR):
    if file in (".DS_Store"): continue
    print(f"Creating test for {file}...")

    try:
        no_opt = helpers.get_bytecode(subprocess.run(f"vyper {CONTRACTS_DIR + file} --optimize none", **standard_kwargs))
        gas_opt = helpers.get_bytecode(subprocess.run(f"vyper {CONTRACTS_DIR + file} --optimize gas", **standard_kwargs))
        size_opt = helpers.get_bytecode(subprocess.run(f"vyper {CONTRACTS_DIR + file} --optimize codesize", **standard_kwargs))
        # old = helpers.get_bytecode(subprocess.run(f"vyper {CONTRACTS_DIR + file}", **standard_kwargs)) # @todo get this to use 3.9
        method_ids = json.loads((subprocess.run(f"vyper -f method_identifiers {CONTRACTS_DIR + file}", **standard_kwargs)).stdout.strip())
        raw_abi = json.loads((subprocess.run(f"vyper -f abi {CONTRACTS_DIR + file}", **standard_kwargs)).stdout.strip())
        # print(raw_abi)

        # create an abi list with name, inputs, selector, and mutability for each fn
        abi = []
        for idx, (sig, sel) in enumerate(method_ids.items()):
            name = sig.split("(")[0]
            args = sig.split("(")[1].split(")")[0].split(",")
            args = [arg.strip() for arg in args if arg.strip() != ""]
            sel = "0x" + sel[2:].zfill(8)
            mutability = "external"
            if name not in ("__init__", "__default__"):
                abi_mut = [fn["stateMutability"] for fn in raw_abi if "name" in fn.keys() and fn["name"] == name][0]
                if abi_mut == "view": mutability = "view"
            abi.append({ "name": name, "inputs": args, "selector": sel, "mutability": mutability })
        # print(abi)

        # separate lists of args for constructor, fns, and views
        constructor_args_list = [f["inputs"] for f in abi if f["name"] == "__init__"]
        constructor_args = constructor_args_list[0] if constructor_args_list else []
        fn_methods = [ f for f in abi if f["name"] != "__init__" and f["mutability"] == "external" ]
        view_methods = [ f for f in abi if f["mutability"] == "view" ]
        # print(fn_methods)

        # calculate how many args are needed for each type & total
        max_fn_args = max([len(fn["inputs"]) for fn in fn_methods]) if len(fn_methods) > 0 else 0
        max_view_args = max([len(fn["inputs"]) for fn in view_methods]) if len(view_methods) > 0 else 0
        total_args = 1 + len(constructor_args) + max_fn_args + max_view_args # [value, const, fn, view]
        # print(total_args)

        # arg[0] will be the msg.value to send, don't need anything
        start = 1

        # constructor args will be added into `encodePacked` bytecodes to deploy
        const_args_to_pass = "" if len(constructor_args) == 0 else "abi.encode("
        for i in range(len(constructor_args)):
            const_args_to_pass += wrap_for_type(constructor_args[i], start + i)
            if i < len(constructor_args) - 1:
                const_args_to_pass += ", "
            else:
                const_args_to_pass += ")"
        start += len(constructor_args)
        # print(const_args_to_pass)

        # fn sel assignment will set fn_sel and cd for each fn
        fn_assignments = []
        for i in range(len(fn_methods)):
            args = ""
            if fn_methods[i]["inputs"] != []:
                args = ", ".join([wrap_for_type(arg, start + idx) for idx, arg in enumerate(fn_methods[i]["inputs"])])
            if i == len(fn_methods) - 1:
                temp = "{"
            else:
                temp = f"if (fn_sel_idx == {i}) {{"
            temp += f"""
            fn_sel = {fn_methods[i]["selector"]};
            cd = abi.encodeWithSelector(fn_sel{", " + args if len(args) > 0 else ""});
        }}"""
            fn_assignments.append(temp)
        fn_sel_assignment = " else ".join(fn_assignments)
        start += max_fn_args
        # print(fn_sel_assignment)

        # view sel assignment will set view_sel and view_calldata for each fn
        view_assignments = []
        for i in range(len(view_methods)):
            args = ""
            if view_methods[i]["inputs"] != []:
                args = ", ".join([wrap_for_type(arg, start + idx) for idx, arg in enumerate(view_methods[i]["inputs"])])

            if i == len(view_methods) - 1:
                temp = "{"
            else:
                temp = f"if (view_sel_idx == {i}) {{"
            temp += f"""
            view_sel = {view_methods[i]["selector"]};
            view_calldata = abi.encodeWithSelector(view_sel{", " + args if len(args) > 0 else ""});
        }}"""
            view_assignments.append(temp)
        view_sel_assignment = " else ".join(view_assignments)
        start += max_view_args
        assert start == total_args
        # print(view_sel_assignment)

        # create output file path
        name = "".join([word.capitalize() for word in file.split(".")[0].split("_")])
        file_path = f"{TESTS_DIR}{name}.t.sol"

        data_to_write = f"""
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import {{ Test, console2 }} from "forge-std/test.sol";

contract {name}Test is Test {{
    function testFormal__{name}(uint256[{total_args}] calldata args, uint8 comp_idx, uint8 fn_sel_idx, uint8 view_sel_idx) external {{
        vm.assume(args[0] < type(uint96).max);
        vm.deal(address(this), args[0] * 6);

        bytes memory unopt_bc = hex"{no_opt}";
        bytes memory bc_args = {const_args_to_pass};
        unopt_bc = abi.encodePacked(unopt_bc{", bc_args" if const_args_to_pass != "" else ""});
        address unopt = _deploy(unopt_bc);

        address comp;
        if (comp_idx == 0) {{
            bytes memory old_bc = hex"INSERT_039_HERE";
            old_bc = abi.encodePacked(unopt_bc{", bc_args" if const_args_to_pass != "" else ""});
            comp = _deploy(old_bc);
        }} else if (comp_idx == 1) {{
            bytes memory gas_bc = hex"{gas_opt}";
            gas_bc = abi.encodePacked(unopt_bc{", bc_args" if const_args_to_pass != "" else ""});
            comp = _deploy(gas_bc);
        }} else {{
            bytes memory size_bc = hex"{size_opt}";
            size_bc = abi.encodePacked(unopt_bc{", bc_args" if const_args_to_pass != "" else ""});
            comp = _deploy(size_bc);
        }}

        assert((comp == address(0)) == (unopt == address(0)));
        if (comp != address(0)) {{
            _compareDeployed(unopt, comp, args, fn_sel_idx, view_sel_idx);
        }}
    }}

    function _deploy(bytes memory bytecode) internal returns (address comp) {{
        assembly {{
            comp := create(0, add(bytecode, 0x20), mload(bytecode))
        }}
    }}

    function _compareDeployed(address unopt, address comp, uint[{total_args}] memory args, uint8 fn_sel_idx, uint8 view_sel_idx) internal {{
        bytes memory cd = mk_calldata(args, fn_sel_idx);
        (bool s_orig, bytes memory d_orig) = unopt.call{{value: args[0]}}(cd);
        (bool s_comp, bytes memory d_comp) = comp.call{{value: args[0]}}(cd);

        assert(s_orig == s_comp);
        assert(d_orig.length == d_comp.length);
        if (d_orig.length > 0) {{
            assert(keccak256(d_orig) == keccak256(d_comp));
        }}

        bytes memory view_calldata = mk_view_calldata(args, view_sel_idx);
        (s_orig, d_orig) = unopt.call(view_calldata);
        (s_comp, d_comp) = comp.call(view_calldata);

        assert(s_orig == s_comp);
        assert(d_orig.length == d_comp.length);
        if (d_orig.length > 0) {{
            assert(keccak256(d_orig) == keccak256(d_comp));
        }}
    }}

    function mk_calldata(uint[{total_args}] memory args, uint8 fn_sel_idx) internal pure returns (bytes memory cd) {{
        bytes4 fn_sel;
        {fn_sel_assignment}
    }}

    function mk_view_calldata(uint[{total_args}] memory args, uint8 view_sel_idx) internal pure returns (bytes memory view_calldata) {{
        bytes4 view_sel;
        {view_sel_assignment}
    }}
}}
    """
        with open(file_path, "w") as file:
            file.write(data_to_write)

    except TypeError as e:
        print(f"Failed to process {file} - {e}")
