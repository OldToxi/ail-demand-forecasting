"""Researched / judgment reference data for the ACCL demand plan.

EVERY value here is an external assumption (not from ACCL sales files) and is labelled with a source:
  [RESEARCH] = published figure (BBS census, BCMA, industry press)
  [JUDGMENT] = analyst estimate (e.g. road-distance tiers), to be refined with real data later

Keeping these in one file makes the assumptions auditable and easy to update.
"""

# ----------------------------------------------------------------------------- market (national)
# [RESEARCH] BCMA / The Daily Star / industry reports (2025)
NATIONAL_DEMAND_MT_2025 = 39_750_000      # national cement demand, MT (2025)
NATIONAL_GROWTH_YOY = 0.0555              # +5.55% YoY (2025 over 2024)
INDUSTRY_CAPACITY_MT = 86_020_000         # 41 plants combined
INDUSTRY_UTILISATION = 0.56               # ~56% sector utilisation

# [RESEARCH] cemnet / akijcement.com
ACCL_CAPACITY_MT = 3_350_000              # ACCL annual capacity, MT
ACCL_PLANT_DISTRICT = "Narayanganj"       # Bandar, Narayanganj

# ----------------------------------------------------------------------------- district populations
# [RESEARCH] Bangladesh Bureau of Statistics, Population & Housing Census 2022 (district totals).
# Used only to ALLOCATE the national market across districts by population weight; the result is then
# CALIBRATED against ACCL's actual district sales, so modest absolute errors wash out.
DISTRICT_POP_2022 = {
    "Dhaka": 14_734_025, "Gazipur": 5_263_474, "Narayanganj": 3_909_138, "Narsingdi": 2_584_452,
    "Manikganj": 1_558_025, "Munshiganj": 1_625_262, "Tangail": 4_037_608, "Kishoreganj": 3_267_630,
    "Faridpur": 2_162_876, "Gopalganj": 1_291_050, "Madaripur": 1_293_027, "Rajbari": 1_189_811,
    "Shariatpur": 1_294_561, "Mymensingh": 5_911_594, "Jamalpur": 2_499_552, "Netrokona": 2_324_282,
    "Sherpur": 1_501_853, "Chattogram": 9_169_464, "Cumilla": 6_212_216, "Brahmanbaria": 3_306_618,
    "Chandpur": 2_636_291, "Noakhali": 3_625_474, "Feni": 1_646_567, "Lakshmipur": 1_940_442,
    "Cox's Bazar": 2_823_265, "Khagrachhari": 714_364, "Rangamati": 647_587, "Bandarban": 481_109,
    "Rajshahi": 2_915_492, "Natore": 1_859_182, "Naogaon": 2_985_690, "Chapainawabganj": 1_824_130,
    "Pabna": 2_818_513, "Sirajganj": 3_442_704, "Bogura": 3_740_000, "Joypurhat": 957_665,
    "Rangpur": 3_169_614, "Dinajpur": 3_315_238, "Gaibandha": 2_562_232, "Kurigram": 2_329_161,
    "Lalmonirhat": 1_428_406, "Nilphamari": 2_089_120, "Panchagarh": 1_141_120, "Thakurgaon": 1_524_010,
    "Khulna": 2_613_998, "Bagerhat": 1_613_076, "Satkhira": 2_281_772, "Jashore": 3_076_875,
    "Jhenaidah": 1_997_240, "Magura": 1_060_130, "Narail": 788_046, "Kushtia": 2_390_282,
    "Chuadanga": 1_313_353, "Meherpur": 705_690, "Barishal": 2_570_450, "Bhola": 1_932_514,
    "Patuakhali": 1_727_637, "Pirojpur": 1_198_970, "Barguna": 1_010_530, "Jhalokati": 682_669,
    "Sylhet": 3_857_037, "Moulvibazar": 2_123_447, "Habiganj": 2_358_886, "Sunamganj": 2_695_495,
}

# ----------------------------------------------------------------------------- freight tiers
# [JUDGMENT] approximate ROAD distance (km) from the plant at Bandar, Narayanganj. A proxy for freight
# economics until real lane rates arrive. Tiers: Near <100, Mid 100-250, Far >250.
DISTRICT_DISTANCE_KM = {
    "Narayanganj": 15, "Dhaka": 25, "Gazipur": 45, "Narsingdi": 50, "Munshiganj": 40,
    "Manikganj": 75, "Brahmanbaria": 90, "Cumilla": 95, "Kishoreganj": 100, "Tangail": 100,
    "Madaripur": 90, "Shariatpur": 70, "Chandpur": 95, "Gopalganj": 130, "Rajbari": 130,
    "Faridpur": 120, "Mymensingh": 120, "Jamalpur": 155, "Netrokona": 160, "Sherpur": 175,
    "Feni": 150, "Noakhali": 165, "Lakshmipur": 150, "Chattogram": 250, "Cox's Bazar": 390,
    "Khagrachhari": 275, "Rangamati": 310, "Bandarban": 330, "Sylhet": 240, "Habiganj": 175,
    "Moulvibazar": 215, "Sunamganj": 260, "Sirajganj": 145, "Pabna": 165, "Natore": 200,
    "Rajshahi": 250, "Chapainawabganj": 290, "Naogaon": 260, "Bogura": 200, "Joypurhat": 265,
    "Rangpur": 300, "Dinajpur": 350, "Gaibandha": 260, "Kurigram": 335, "Lalmonirhat": 340,
    "Nilphamari": 340, "Panchagarh": 400, "Thakurgaon": 385, "Kushtia": 210, "Chuadanga": 245,
    "Meherpur": 265, "Jhenaidah": 220, "Magura": 190, "Narail": 180, "Jashore": 220,
    "Satkhira": 260, "Bagerhat": 220, "Khulna": 230, "Barishal": 150, "Jhalokati": 165,
    "Pirojpur": 180, "Bhola": 195, "Patuakhali": 205, "Barguna": 210,
}


def freight_tier(dist_km):
    if dist_km is None:
        return "Unknown"
    if dist_km < 100:
        return "Near"
    if dist_km <= 250:
        return "Mid"
    return "Far"
