# Service module: server_test
class server_test:
    def __init__(self, server=None):
        self.server = server

    def does_it_work(self, *args):
        return 'It Works!'

    def default(self, *args):
        return 'It Works!'

