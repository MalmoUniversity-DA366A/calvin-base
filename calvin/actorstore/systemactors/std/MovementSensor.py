# MovementSensor actor for Calvin arduino
# Author: Daniel Nordahl

from calvin.actor.actor import Actor, ActionResult, manage, condition


class MovementSensor(Actor):
    """
    Produce next integer in a sequence 1,2,3,...
    Outputs:
      integer : Integer
    """

    @manage(['count'])
    def init(self):
        self.count = 0

    @condition(action_output=['integer'])
    def cnt(self):
        self.count = 1
        return ActionResult(production=(self.count, ))

    action_priority = (cnt,)

    def report(self):
        return self.count

    test_args = []
    test_set = [
        {'in': {}, 'out': {'integer': [n]}} for n in range(1, 10)
    ]
