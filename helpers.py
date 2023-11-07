def get_bytecode(shell_return):
    tmp = shell_return.stdout.strip()
    idx = tmp.find("0x")
    if idx == -1:
        raise()
    return tmp[idx + 2:]
