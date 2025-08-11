Applicazione Django per il coding con integrazione API

Per avviare l'applicazione:
1. Installa le dipendenze con `pip install -r requirements.txt`.
2. Esegui le migrazioni con `python manage.py migrate`.
3. Avvia il server di sviluppo con `python manage.py runserver`.

La pagina principale permette di inserire il nome. Premendo "OK" viene eseguita una richiesta AJAX al backend che verifica
l'esistenza di un utente `UtenteApi` con quel nome. Se trovato appare un messaggio di benvenuto.
