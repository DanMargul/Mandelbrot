### `price-options`

| track | fixed overhead | ns per option | relative | largest run |
|---|---:|---:|---:|---:|
| cpp_pure | 2 ms | 3758.1 | 1.00x | 400,000 in 1.51 s |
| python_cpp | 30 ms | 4311.2 | 1.15x | 400,000 in 1.75 s |
| python_pure | 30 ms | 4682.4 | 1.25x | 400,000 in 1.90 s |

### `invert-implied-volatility`

| track | fixed overhead | ns per option | relative | largest run |
|---|---:|---:|---:|---:|
| cpp_pure | 3 ms | 3885.9 | 1.00x | 400,000 in 1.56 s |
| python_cpp | 27 ms | 4506.6 | 1.16x | 400,000 in 1.83 s |
| python_pure | 31 ms | 23042.4 | 5.93x | 400,000 in 9.25 s |
