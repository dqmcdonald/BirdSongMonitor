# Prints out species list for Christchurch

from birdnetlib.species import SpeciesList
from datetime import datetime

LONGITUDE =  172.72602916819974
LATITUDE =  -43.62674558206582

species = SpeciesList()
species_list = species.return_list(
    lon=LONGITUDE, lat=LATITUDE, date=datetime(year=2025, month=9, day=11)
)


for s in species_list:
    cn = s["common_name"]
    sn = s["scientific_name"]
    print(f"{cn:<25} : {sn} ")
