import os
import subprocess
import json
import helpers

CONTRACTS_DIR = "pipeline/contracts/"
TESTS_DIR = "pipeline/formal/test/"
standard_kwargs = {"shell": True, "stdout": subprocess.PIPE, "check": True, "text": True}

# TURN OFF VENV AND RUN THIS TO ADD THE 0.3.9 BYTECODE IN
for file in os.listdir(CONTRACTS_DIR):
    if file in (".DS_Store"): continue
    print(f"Replacing old bytecode for {file}...")
    try:
        old = helpers.get_bytecode(subprocess.run(f"vyper {CONTRACTS_DIR + file}", **standard_kwargs))
        name = "".join([word.capitalize() for word in file.split(".")[0].split("_")])
        test_file_path = f"{TESTS_DIR}{name}.t.sol"

        with open(test_file_path, "r") as file:
            contents = file.read()

        updated = contents.replace("INSERT_039_HERE", old)

        with open(test_file_path, "w") as file:
            file.write(updated)

    except:
        print(f"Failed to process {file}")
