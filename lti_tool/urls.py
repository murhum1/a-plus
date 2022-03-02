from django.conf.urls import url

from . import views


urlpatterns = [
    url(r'^lti_login/$',
        views.lti_login),
    url(r'^lti_launch/$',
        views.lti_launch),
    
]