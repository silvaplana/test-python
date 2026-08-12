import json

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from .financialbalance import FinancialBalance, FinancialBalanceAnalysisError


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
        self.app.get("/financialbalance/analysis")(self.getAnalysis)
        self.app.post("/financialbalance/analyses")(self.saveAnalysis)
        self.app.get("/financialbalance/analyses/latest")(self.getLatestAnalysis)

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

    def getAnalysis(self) -> StreamingResponse:
        """Endpoint REST GET /financialbalance/analysis. Lance l'analyse IA
        de la derniere archive de releves envoyee et retourne un flux
        Server-Sent Events : des evenements {"type": "progress", ...}
        pendant que l'IA travaille, puis un evenement final {"type":
        "result", "data": {...}} avec le bilan structure, ou {"type":
        "error", "message": ...} en cas d'echec.

        GET (pas POST) : ne prend aucun parametre (utilise la derniere
        archive stockee) et doit rester consommable par EventSource cote
        navigateur, qui ne supporte que GET.
        """

        def event_stream():
            try:
                for event in self.client.analyze_latest_archive():
                    yield f"data: {json.dumps(event)}\n\n"
            except FinancialBalanceAnalysisError as exc:
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    def saveAnalysis(self, analysis: dict) -> dict:
        """Endpoint REST POST /financialbalance/analyses. Sauvegarde un
        bilan (celui reçu de GET /financialbalance/analysis) pour pouvoir
        le reafficher plus tard sans relancer une analyse IA.
        """
        try:
            return self.client.save_analysis(analysis)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def getLatestAnalysis(self) -> dict:
        """Endpoint REST GET /financialbalance/analyses/latest. Retourne le
        dernier bilan sauvegarde, ou 404 si aucun n'a encore ete sauvegarde.
        """
        try:
            return self.client.get_latest_analysis()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
