from fastapi import FastAPI, HTTPException, UploadFile

from .financialbalance import FinancialBalance


class FinancialBalanceReceiver:
    """Recoit les requetes REST (FastAPI) et delegue a FinancialBalance.

    Comme les autres receivers, enregistre ses routes sur une app FastAPI
    existante (partagee avec les autres modules), pas de service dedie.
    """

    def __init__(self, client: FinancialBalance, app: FastAPI) -> None:
        self.client = client
        self.app = app
        self._register_routes()

    def _register_routes(self) -> None:
        self.app.post("/financialbalance/archives")(self.sendBankAccountArchives)

    async def sendBankAccountArchives(self, file: UploadFile) -> dict:
        """Endpoint REST POST /financialbalance/archives. Recoit une archive
        zip des releves bancaires (compte courant + Livret bleu) et la stocke.

        Un upload de fichier ne peut techniquement pas se faire en GET (pas
        de corps de requete) : passe donc par POST (multipart/form-data),
        meme si le nom de la methode (sendBankAccountArchives, pas
        getBankAccountArchives) suit plutot la convention setX/sendX des
        endpoints d'ecriture de ce backend (ex: MotorReceiver.setMotor).
        """
        content = await file.read()
        try:
            return self.client.save_bank_account_archive(file.filename or "", content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
