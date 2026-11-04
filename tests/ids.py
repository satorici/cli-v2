def pid(prefix: str, n: int) -> str:
    """A valid public ID (21 letters and digits) that reads like `fnd000…010`."""
    return f"{prefix}{n:0{21 - len(prefix)}d}"
