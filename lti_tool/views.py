from django.http import HttpResponse
from django.views.decorators.http import require_POST
from django.conf import settings
from pylti1p3.contrib.django import DjangoOIDCLogin, DjangoMessageLaunch, DjangoCacheDataStorage

def get_launch_url(request):
    target_link_uri = request.POST.get('target_link_uri', request.GET.get('target_link_uri'))
    if not target_link_uri:
        raise Exception('Missing "target_link_uri" param')
    return target_link_uri

def get_tool_conf():
    return settings.LTI_TOOL_CONF

def get_launch_data_storage():
    return DjangoCacheDataStorage()

def lti_login(request):
    print(request.POST)
    tool_conf = get_tool_conf()
    launch_data_storage = get_launch_data_storage()

    oidc_login = DjangoOIDCLogin(request, tool_conf, launch_data_storage=launch_data_storage)
    target_link_uri = get_launch_url(request)
    return oidc_login.redirect(target_link_uri)

@require_POST
def lti_launch(request):
    print(request.POST)
    tool_conf = get_tool_conf()
    launch_data_storage = get_launch_data_storage()
    message_launch = DjangoMessageLaunch(request, tool_conf, launch_data_storage=launch_data_storage)
    message_launch_data = message_launch.get_launch_data()
    print(message_launch_data)
    name = message_launch_data.get('https://purl.imsglobal.org/spec/lti/claim/custom', {}).get('name', None)
    print(name)

    return HttpResponse('Hello from A+!')