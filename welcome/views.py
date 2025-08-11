import json
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from .models import UtenteApi


def index(request):
    return render(request, 'welcome/index.html')


def chat_persona(request):
    return render(request, 'welcome/chat.html')


@csrf_exempt
def check_user(request):
    data = json.loads(request.body.decode('utf-8'))
    name = data.get('name')
    try:
        user = UtenteApi.objects.get(nome=name)
        return JsonResponse({'exists': True, 'nome': user.nome})
    except UtenteApi.DoesNotExist:
        return JsonResponse({'exists': False})
