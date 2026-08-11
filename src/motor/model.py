class MotorModel:
    """Modele metier representant le moteur (nom courant)."""

    def __init__(self, motorName: str = "") -> None:
        self.motorName = motorName

    def getMotor(self) -> str:
        """Getter de motorName."""
        print("GetMotor called: returns " + self.motorName)
        return self.motorName

    def setMotor(self, motorName: str) -> None:
        """Setter de motorName."""
        print("SetMotor called with value " + motorName)
        self.motorName = motorName
