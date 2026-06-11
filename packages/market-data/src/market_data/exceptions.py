class DataMissingError(Exception):
    """Raised when the entire contract directory is absent from the tick store.

    Indicates a configuration error (wrong ticks_dir, data never collected) rather
    than a normal sparse-gap scenario.  The message includes symbol, sec_type, and
    the expected filesystem path so the operator can locate the problem immediately.
    """
