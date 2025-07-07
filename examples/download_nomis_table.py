from kindtech.nomis import get_ons_table

table = get_ons_table("NM_1_1")
print(table)
geo_table = get_ons_table(
    "NM_1_1",
    geography="TYPE480",
    time="latest",
    measures=20100,
    item=1,
    select=["geography_name", "sex_name", "obs_value"],
)
print(geo_table)
