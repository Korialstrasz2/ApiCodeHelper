from django.urls import path
from . import views
from .programming_helper_chatbot import programming_helper_send_message
from .chatbot_utils import personas_list

urlpatterns = [
    path('', views.index, name='index'),
    path('check_user/', views.check_user, name='check_user'),
    path('chat/', views.chat_persona, name='chat_persona'),
    path('api/programming_helper/', programming_helper_send_message, name='programming_helper_send_message'),
    path('api/personas/', personas_list, name='personas_list'),
]
