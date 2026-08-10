from scenario.representative import Representative
from scenario.venue import Venue


class Group:
    venue: Venue
    members: set[str]

    def __init__(self, venue: Venue, members: set[str]):
        self.venue = venue
        self.members = members