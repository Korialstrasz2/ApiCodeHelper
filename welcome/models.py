from django.db import models

class UtenteApi(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    eta = models.IntegerField()
    passphrase = models.CharField(max_length=200)

    def __str__(self) -> str:
        return self.nome

class Persona(models.Model):
    nome = models.CharField(max_length=128)
    versione = models.CharField(max_length=32, default="1")
    contenuto = models.TextField()
    inglese = models.BooleanField(default=False)
    ristretto = models.BooleanField(default=False)
    esperienze = models.TextField(
        blank=True, null=True,
        help_text="Elenco (anche lungo) di avventure già vissute dal personaggio"
    )
    class Meta:
        unique_together = ('nome', 'versione')

    def __str__(self):
        return f"{self.nome} v{self.versione}"