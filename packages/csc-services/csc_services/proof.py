from csc_services import Service

class Proof(Service):
    """Proof of concept service"""
    def __init__(self, service_layer=None):
        super().__init__()
    
    def run(self, *args):
        """Execute proof of concept"""
        return "It Worked!"
    
    def default(self, *args):
        """Default handler"""
        return "It Worked!"
