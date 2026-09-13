"""Fictional name pools, split by sex and birth decade.

Committed seed data rather than a Faker dependency, for three reasons: byte
identical regeneration cannot break on a library bump, the over-match anomaly
needs households that genuinely share surnames, and cohort-correct given names
(a 1948 cohort gets Linda and Robert, a 2019 cohort gets Olivia and Liam) cost
nothing here and make the data read as real.

Every name below is a common American name used in a wholly fabricated dataset.
No row corresponds to any real person.
"""
from __future__ import annotations

SURNAMES = [
    "Abbott", "Ackerman", "Alvarez", "Amato", "Archer", "Ashford", "Atwood",
    "Bainbridge", "Ballard", "Banks", "Barlow", "Barrett", "Bascomb", "Baxter",
    "Beckett", "Beltran", "Bennett", "Bergeron", "Blackwell", "Blanchard",
    "Bledsoe", "Bolton", "Bowers", "Braddock", "Bradshaw", "Brennan", "Bridges",
    "Brockman", "Bronson", "Buchanan", "Burkhart", "Byrne", "Caldwell",
    "Calloway", "Cardenas", "Carmichael", "Carrington", "Castellano", "Cavanaugh",
    "Chamberlain", "Chandler", "Chastain", "Cho", "Clayborne", "Colfax",
    "Conroy", "Copeland", "Cormier", "Cortland", "Cosgrove", "Crandall",
    "Crawford", "Cromwell", "Cunningham", "Dalton", "Danforth", "Darnell",
    "Davenport", "Delacroix", "Delgado", "Demarco", "Devlin", "Dorsey",
    "Draper", "Driscoll", "Duarte", "Dunleavy", "Eastman", "Eckhart",
    "Ellsworth", "Emerson", "Escobar", "Everhart", "Fairbanks", "Falkner",
    "Farrow", "Fenwick", "Ferraro", "Finnegan", "Fitzgerald", "Fleischer",
    "Fontaine", "Forsythe", "Fairchild", "Gallagher", "Garrison", "Gentry",
    "Gilliam", "Goddard", "Goldstein", "Granados", "Grantham", "Greenwood",
    "Griffith", "Guerrero", "Hadley", "Halloran", "Hammond", "Harlow",
    "Hartnett", "Hathaway", "Havens", "Hawthorne", "Hayashi", "Henderson",
    "Hendricks", "Hollister", "Holloway", "Hopkins", "Horvath", "Huang",
    "Hutchins", "Ingram", "Iverson", "Jankowski", "Jarrett", "Jennings",
    "Kaminski", "Keating", "Kellerman", "Kendrick", "Kerrigan", "Kilgore",
    "Kimball", "Kingsley", "Kirkland", "Knowles", "Kovacs", "Lachance",
    "Ladner", "Lambert", "Langford", "Larkin", "Lassiter", "Leclair",
    "Lindquist", "Littleton", "Lockhart", "Lombardi", "Lovelace", "Lucero",
    "Ludwig", "Mackenzie", "Maddox", "Magnuson", "Mahoney", "Mancini",
    "Marchetti", "Markham", "Marlowe", "Mathers", "McAllister", "McBride",
    "McClintock", "McCormack", "McGrath", "McKinney", "Medeiros", "Mercado",
    "Merrick", "Mikkelsen", "Milbourne", "Montague", "Montoya", "Moreland",
    "Morrissey", "Mulcahy", "Nakamura", "Navarro", "Newcomb", "Nguyen",
    "Nicholson", "Nordstrom", "Oakley", "Okafor", "Olivares", "Ondrejka",
    "Osgood", "Ostrowski", "Padilla", "Palmer", "Parrish", "Pemberton",
    "Pennington", "Perkins", "Petrov", "Pfeiffer", "Pickering", "Pomeroy",
    "Prescott", "Quintero", "Radcliffe", "Ramsey", "Rasmussen", "Redmond",
    "Renteria", "Ridley", "Rosales", "Rothman", "Rowland", "Rutherford",
    "Salisbury", "Sandoval", "Sawyer", "Schuyler", "Sedgwick", "Selby",
    "Sheridan", "Sinclair", "Solberg", "Sorrentino", "Stafford", "Stanton",
    "Sterling", "Stoddard", "Strickland", "Sullivan", "Sutherland", "Tanaka",
    "Tavares", "Templeton", "Thackeray", "Thibodeaux", "Thorne", "Tillman",
    "Torrance", "Trevino", "Underwood", "Vandenberg", "Vasquez", "Vaughn",
    "Vickers", "Villanueva", "Wadsworth", "Wainwright", "Waverly", "Weatherby",
    "Westbrook", "Whitaker", "Whitfield", "Wickham", "Winslow", "Wolcott",
    "Woodard", "Yamamoto", "Yates", "Zabala", "Zamora", "Zeller",
]

# Given names by birth decade. Keys are the decade floor of the birth year.
MALE_NAMES = {
    1930: ["Robert", "James", "John", "William", "Richard", "Charles", "Donald",
           "George", "Thomas", "Joseph", "Harold", "Kenneth"],
    1940: ["James", "Robert", "John", "William", "Richard", "David", "Michael",
           "Ronald", "Larry", "Dennis", "Gary", "Wayne"],
    1950: ["Michael", "David", "James", "Robert", "John", "William", "Mark",
           "Richard", "Steven", "Thomas", "Gary", "Jeffrey"],
    1960: ["Michael", "David", "John", "James", "Robert", "Mark", "William",
           "Richard", "Thomas", "Jeffrey", "Steven", "Brian"],
    1970: ["Michael", "Christopher", "Jason", "David", "James", "John", "Robert",
           "Brian", "William", "Matthew", "Joseph", "Daniel"],
    1980: ["Michael", "Christopher", "Matthew", "Joshua", "David", "Daniel",
           "James", "Robert", "John", "Joseph", "Jason", "Justin"],
    1990: ["Michael", "Christopher", "Matthew", "Joshua", "Jacob", "Nicholas",
           "Andrew", "Daniel", "Tyler", "Joseph", "Brandon", "Austin"],
    2000: ["Jacob", "Michael", "Joshua", "Matthew", "Ethan", "Andrew", "Daniel",
           "Anthony", "Christopher", "Joseph", "William", "Alexander"],
    2010: ["Noah", "Liam", "Jacob", "Mason", "William", "Ethan", "Michael",
           "Alexander", "James", "Elijah", "Benjamin", "Logan"],
    2020: ["Liam", "Noah", "Oliver", "Elijah", "James", "William", "Benjamin",
           "Lucas", "Henry", "Theodore", "Jack", "Levi"],
}

FEMALE_NAMES = {
    1930: ["Mary", "Barbara", "Patricia", "Dorothy", "Betty", "Shirley", "Joan",
           "Margaret", "Nancy", "Helen", "Carol", "Joyce"],
    1940: ["Mary", "Linda", "Barbara", "Patricia", "Carol", "Sandra", "Nancy",
           "Judith", "Sharon", "Karen", "Susan", "Donna"],
    1950: ["Mary", "Linda", "Patricia", "Susan", "Deborah", "Barbara", "Debra",
           "Karen", "Nancy", "Donna", "Cynthia", "Sandra"],
    1960: ["Lisa", "Mary", "Susan", "Karen", "Kimberly", "Patricia", "Linda",
           "Donna", "Michelle", "Cynthia", "Sandra", "Laura"],
    1970: ["Jennifer", "Amy", "Melissa", "Michelle", "Kimberly", "Lisa",
           "Angela", "Heather", "Stephanie", "Nicole", "Jessica", "Elizabeth"],
    1980: ["Jessica", "Jennifer", "Amanda", "Ashley", "Sarah", "Stephanie",
           "Melissa", "Nicole", "Elizabeth", "Heather", "Tiffany", "Michelle"],
    1990: ["Jessica", "Ashley", "Emily", "Samantha", "Sarah", "Amanda",
           "Brittany", "Elizabeth", "Taylor", "Megan", "Hannah", "Lauren"],
    2000: ["Emily", "Madison", "Emma", "Olivia", "Hannah", "Abigail", "Isabella",
           "Samantha", "Elizabeth", "Ashley", "Alexis", "Sarah"],
    2010: ["Sophia", "Emma", "Olivia", "Isabella", "Ava", "Mia", "Emily",
           "Abigail", "Madison", "Charlotte", "Harper", "Amelia"],
    2020: ["Olivia", "Emma", "Charlotte", "Amelia", "Sophia", "Isabella", "Ava",
           "Mia", "Evelyn", "Luna", "Harper", "Camila"],
}

MIDDLE_INITIALS = list("ABCDEFGHIJKLMNPRSTVW")


def _decade_bucket(birth_year: int) -> int:
    """Clamp a birth year to an available decade key."""
    decade = (birth_year // 10) * 10
    keys = sorted(MALE_NAMES)
    if decade < keys[0]:
        return keys[0]
    if decade > keys[-1]:
        return keys[-1]
    return decade


def given_name_pool(sex: str, birth_year: int) -> list[str]:
    table = FEMALE_NAMES if sex == "F" else MALE_NAMES
    return table[_decade_bucket(birth_year)]
