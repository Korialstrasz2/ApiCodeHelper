from django.db import models

class UtenteApi(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    eta = models.IntegerField()
    passphrase = models.CharField(max_length=200)

    def __str__(self) -> str:
        return self.nome
