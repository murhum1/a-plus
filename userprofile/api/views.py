from rest_framework import filters, viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.settings import api_settings

from lib.api.filters import FieldValuesFilter
from lib.api.mixins import ListSerializerMixin, MeUserMixin
from lib.api.constants import REGEX_INT_ME

from ..models import UserProfile
from ..permissions import IsTeacherOrAdminOrSelf
from .serializers import UserBriefSerializer
from .full_serializers import UserSerializer


class UserViewSet(ListSerializerMixin,
                  MeUserMixin,
                  viewsets.ReadOnlyModelViewSet):
    """
    The `users` endpoint returns information about users.

    Operations
    ----------

    `GET /users/?search=email@address.com`:
        returns a list of users matching the exact email address.
        The search parameter is required and must be a valid email.

    `GET /users/<user_id>/`:
        returns the details of a specific user.

    `GET /users/me/`:
        returns the details of the current user.
    """
    permission_classes = api_settings.DEFAULT_PERMISSION_CLASSES + [
        IsTeacherOrAdminOrSelf,
    ]
    filter_backends = (
        IsTeacherOrAdminOrSelf,
        filters.SearchFilter,
    )
    search_fields = ['=user__email']
    lookup_field = 'user_id' # UserProfile.user.id
    lookup_url_kwarg = 'user_id'
    lookup_value_regex = REGEX_INT_ME
    listserializer_class = UserBriefSerializer
    serializer_class = UserSerializer
    queryset = UserProfile.objects.all()

    def get_queryset(self):
        """
        Only return users when searching by exact email address.
        Prevents listing all users.
        """
        # If no search parameter, return empty queryset
        if not self.request.query_params.get('search'):
            return UserProfile.objects.none()

        # Get the base queryset
        queryset = super().get_queryset()

        return queryset


class MeDetail(APIView):
    """
    The `me` endpoint returns information about the current user.

    Operations
    ----------

    `GET /me/`:
        returns the details of the current user.
    """
    def get(self, request, version, format=None): # pylint: disable=unused-argument redefined-builtin
        userinstance = self.request.user.userprofile

        serializer = UserSerializer(userinstance, context={
                        'request': request,
                        })
        return Response(serializer.data)
