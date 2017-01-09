class ListSerializerMixin(object):
    # FIXME: use rest_framework_extensions.mixins.DetailSerializerMixin
    def get_serializer_class(self):
        if self.action == 'list':
            return getattr(self, 'listserializer_class', self.serializer_class)
        return super(ListSerializerMixin, self).get_serializer_class()


class MeUserMixin(object):
    me_user_url_kw = 'user_id'
    me_user_value = 'me'

    # Hook into `initial` method call chain.
    # after calling `initial` we have done all authentication related tasks,
    # so there is valid request.user.
    # NOTE: this though means the kwargs passed to get method and self.kwargs are different
    # Generic methods in framework do not use function parameters, so this is fine.

    def initial(self, request, *args, **kwargs):
        super(MeUserMixin, self).initial(request, *args, **kwargs)

        kw = self.me_user_url_kw
        value = self.kwargs.get(kw, None)
        if value and self.me_user_value == value:
            self.kwargs[kw] = request.user.id
