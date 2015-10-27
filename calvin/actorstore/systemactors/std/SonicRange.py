# Sonic range actor

from calvin.actor.actor import Actor, ActionResult, manage, condition, guard


class SonicRange(Actor):
    """
    Send predetermined data on output.
    Outputs:
      token : Some data
    """
    @manage(['data', 'n', 'dump'])
    def init(self, data, n=1, dump=False):
        self.data = data
        self.n = n
        self.dump = dump

    def log(self, data):
        print "%s<%s>: %s" % (self.__class__.__name__, self.id, data)

    @condition([], ['token'])
    @guard(lambda self: self.n > 0 or self.n == -1)
    def send_it(self):
        if self.n > 0:
            self.n -= 1
        if self.dump:
            self.log(self.data)
        return ActionResult(production=(self.data,))

    action_priority = (send_it, )

    test_args = (42,)
    test_kwargs = {"n": 3}

    test_set = [
        {
            'in': {},
            'out': {'token': [42]}
        } for i in range(3)
    ]

    test_set += [
        {
            'in': {},
            'out': {'token': []}
        }
    ]
