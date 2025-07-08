from kindtech.ons import load_ons

if __name__ == "__main__":
    table = load_ons("NM_1_1")
    print(table)
    geo_table = load_ons(
        "NM_1_1",
        geography="TYPE480",
        time="latest",
        measures=20100,
        item=1,
        select=["geography_name", "sex_name", "obs_value"],
    )
    print(geo_table)
