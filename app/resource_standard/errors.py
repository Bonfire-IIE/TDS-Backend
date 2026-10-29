class ValidationFailed(ValueError):
    def __init__(self, code, *, field=None):
        self.code, self.field = code, field
        super().__init__(f"{field}: {code}" if field else code)
