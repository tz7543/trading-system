import pyarrow as pa

TICK_SCHEMA = pa.schema([
    ("timestamp", pa.timestamp("us", tz="UTC")),
    ("symbol", pa.string()),
    ("bid", pa.float64()),
    ("ask", pa.float64()),
    ("last", pa.float64()),
    ("volume", pa.int64()),
    ("model_delta", pa.float64()),
    ("model_gamma", pa.float64()),
    ("model_vega", pa.float64()),
    ("model_theta", pa.float64()),
    ("model_iv", pa.float64()),
    ("model_underlying", pa.float64()),
])
