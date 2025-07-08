from kindtech.ons._ingestion import create_nomis_tables_dataset

if __name__ == "__main__":
    # This will process ALL datasets (may take 10-30 minutes)
    full_dataset = create_nomis_tables_dataset()
    full_dataset.to_csv("nomis_tables_full.csv", index=False)
