## Getting the data

The raw data is not stored in this repository because the files are too large.
To download it:

1. Go to https://www.usaspending.gov/download_center/award_data_archive
2. Select agency: Department of Veterans Affairs
3. Select award type: Contracts
4. Select fiscal year: 2017, and download the Full file
5. Repeat step 4 for fiscal years 2018 and 2019
6. Unzip the downloads and place the three CSV files in the `Data/` folder
7. Run `./Data/load_data.sh` to load them into PostgreSQL

Expected row counts: 2017 = 220,729, 2018 = 184,728, 2019 = 133,995
