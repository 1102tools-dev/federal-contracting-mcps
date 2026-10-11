# Public SAM extract fixtures

Records are saved slices of SAM.gov's public download files, with no sensitive/FOUO extracts. Entity opt-out records are excluded from saved real fixtures. Unit tests synthesize malformed or opt-out fields in memory.

- `entities.dat`: 35 visible records from `SAM_PUBLIC_UTF-8_MONTHLY_V2_20261005.ZIP`.
- `entities-sba.dat`: three visible records with SBA certification codes/dates from that file.
- `entities-extra.dat`: 100 additional visible active entities from the same file, for independent live parity sampling.
- `exclusions_v2_26283_slice.csv`: 16 records spanning classifications and quoted/multiline fields from `SAM_Exclusions_Public_Extract_V2_26283.ZIP` (October 10, 2026).
- `exclusions_v2_26283_firms.csv`: 60 real active firms with UEIs from the same file, for independent live parity sampling.

Entity fixture BOF/EOF counts are adjusted to the slice size; row values are preserved. Exclusions retain the real header and CSV row values.

Sources: `https://sam.gov/api/prod/fileextractservices/v1/api/listfiles?domain=Entity%20Registration/Public%20V2&privacy=Public` and the corresponding `Exclusions/Public V2` listing. Loaders pick the newest expected public filename by modification date, download without a SAM API key, and report the extract date encoded in the filename.
