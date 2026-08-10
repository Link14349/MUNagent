from scenario.scenario import Scenario


class Simulator:
    scenario: Scenario

    def __init__(self, scenario: Scenario):
        self.scenario = scenario

    def run(self):
        pass