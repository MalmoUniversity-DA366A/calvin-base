#Author: Daniel Nordahl 2015-10-27
#
#Calvin-Arduino rage actor. Reads input from a sonic range
#sensor and send the data as a token to a std actor.

from calvin.actor.actor import Actor, ActionResult, manage, condition

class SonicRange(Actor):
	"""
	forward a token unchanged
	Inputs:
	  token : a token
	Outputs:
	  token : the same token
	"""

	@manage(['dump'])
	def init(self, dump = False):
		self.dump = dump

	def log(self,data):
		print "%s<%s>: %s" % (self.__class__.__name__, self.id, data)


    @condition(['token'], ['token'])
    def donothing(self, input):
        if self.dump : self.log(input)
        return ActionResult(tokens_consumed=1, tokens_produced=1, production=( input, ))


	action_priority = ( donothing, )








