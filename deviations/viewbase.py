from itertools import groupby
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Type
import datetime

from django.db import models
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.contrib import messages
from django import forms
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _, ngettext

from course.models import CourseModule, UserTag
from course.viewbase import CourseInstanceMixin, CourseInstanceBaseView
from deviations.models import SubmissionRuleDeviation, DeadlineRuleDeviation
from lib.helpers import is_ajax
from lib.viewbase import BaseFormView, BaseRedirectView
from authorization.permissions import ACCESS
from exercise.models import BaseExercise
from userprofile.models import UserProfile


class ListDeviationsView(CourseInstanceBaseView):
    access_mode = ACCESS.TEACHER
    deviation_model: Type[SubmissionRuleDeviation]

    def get_common_objects(self) -> None:
        super().get_common_objects()
        self.deviations = self.deviation_model.objects.filter(
            Q(exercise__course_module__course_instance=self.instance)
            | Q(module__course_instance=self.instance)
        )
        self.note("deviations")


class AddDeviationsView(CourseInstanceMixin, BaseFormView):
    access_mode = ACCESS.TEACHER
    deviation_model: Type[SubmissionRuleDeviation]
    session_key: str

    def get_context_data(self, **kwargs: Any) -> dict:
        context = super().get_context_data(**kwargs)
        if self.request.GET.get('previous'):
            context.update({'cancel_action': self.request.GET.get('previous')})
        else:
            context.update({'cancel_action': self.instance.get_url('deviations-list-dl')})
        return context

    def get_form_kwargs(self) -> Dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.instance
        return kwargs

    def get_initial_get_param_spec(self) -> Dict[str, Optional[Callable[[str], Any]]]:
        def list_arg(arg):
            return arg.split(",")

        spec = super().get_initial_get_param_spec()
        spec.update({
            "module": list_arg,
            "exercise": list_arg,
            "submitter": list_arg,
            "submitter_tag": list_arg,
        })
        return spec

    def form_valid(self, form: forms.BaseForm) -> HttpResponse:
        exercises = form.cleaned_data.get('exercise', [])
        submitters = get_submitters(form.cleaned_data)
        modules = form.cleaned_data.get('module', [])
        existing_deviations = self.deviation_model.objects.filter(
            Q(exercise__in=exercises) | Q(module__in=modules),
            submitter__in=submitters,
        )

        if existing_deviations:
            # Some deviations already existed. Use OverrideDeviationsView to
            # confirm which ones the user wants to override. Store the form
            # values in the current session, so they can be used afterwards.
            self.success_url = self.deviation_model.get_override_url(self.instance)
            self.request.session[self.session_key] = self.serialize_session_data(form.cleaned_data)
        else:
            self.success_url = self.get_success_no_override_url()

            for submitter in submitters:
                for exercise in exercises:
                    new_deviation = self.deviation_model(
                        exercise=exercise,
                        submitter=submitter,
                        granter=self.request.user.userprofile,
                    )
                    new_deviation.update_by_form(form.cleaned_data)
                    new_deviation.save()
                for module in modules:
                    new_deviation = self.deviation_model(
                        module=module,
                        submitter=submitter,
                        granter=self.request.user.userprofile,
                    )
                    new_deviation.update_by_form(form.cleaned_data)
                    new_deviation.save()
            messages.success(self.request, _("SUCCESS_ADDING_DEVIATIONS"))
        return super().form_valid(form)

    def serialize_session_data(self, form_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert input form data into serializable values that can be stored in
        the session cache.
        """
        result = {}
        for key in ('exercise', 'module', 'submitter', 'submitter_tag'):
            result[key] = [i.id for i in form_data.get(key, [])]
        return result


class OverrideDeviationsView(CourseInstanceMixin, BaseFormView):
    access_mode = ACCESS.TEACHER
    # form_class is not really used, but it is required by the FormView.
    # The form contains only checkboxes and the user input is validated in
    # the form_valid method. The form HTML is manually written in the template.
    form_class = forms.Form
    deviation_model: Type[SubmissionRuleDeviation]
    session_key: str

    def get_common_objects(self) -> None:
        super().get_common_objects()
        self.session_data = self.deserialize_session_data(self.request.session[self.session_key])
        self.exercises = self.session_data.get('exercise', [])
        self.modules = self.session_data.get('module', [])
        self.submitters = get_submitters(self.session_data)
        self.existing_deviations = self.deviation_model.objects.filter(
            Q(exercise__in=self.exercises) | Q(module__in=self.modules),
            submitter__in=self.submitters,
        )
        self.new_deviation_seconds = new_deviation_seconds(
            self.existing_deviations[0],
            self.session_data.get('seconds'),
            self.session_data.get('new_date')
        )
        self.new_deviation_date = new_deviation_date(
            self.existing_deviations[0],
            self.session_data.get('seconds'),
            self.session_data.get('new_date')
        )
        self.note("session_data", "exercises", "submitters", "existing_deviations",
                   "new_deviation_date", "new_deviation_seconds")

    def form_valid(self, form: forms.BaseForm) -> HttpResponse:
        self.override_deviations = set()
        deviation_list = self.request.POST.getlist('override')
        for id_group in deviation_list:
            try:
                submitter_id, exercise_id, module_id = id_group.split('.')
                submitter_id = int(submitter_id)
                exercise_id = int(exercise_id) if exercise_id.isdigit() else None
                module_id = int(module_id) if module_id.isdigit() else None
                self.override_deviations.add((submitter_id, exercise_id, module_id))
            except ValueError:
                messages.error(self.request,
                    format_lazy(
                        _("INVALID_EXERCISE_OR_SUBMITTER_ID -- {id}"),
                        id=id_group,
                    )
                )
                continue

        self.existing_deviations = {(d.submitter_id, d.exercise_id, d.module_id): d for d in self.existing_deviations}

        for submitter in self.submitters:
            for exercise in self.exercises:
                self.create_or_update_deviation(submitter, exercise, None)
            for module in self.modules:
                self.create_or_update_deviation(submitter, None, module)

        del self.request.session[self.session_key]
        messages.success(self.request, _("SUCCESS_OVERRIDING_DEVIATIONS"))
        return super().form_valid(form)

    def deserialize_session_data(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert serialized session data back into its original representation.
        """
        result = {
            'exercise': BaseExercise.objects.filter(id__in=session_data.get('exercise', [])),
            'module': CourseModule.objects.filter(id__in=session_data.get('module', [])),
            'submitter': UserProfile.objects.filter(id__in=session_data.get('submitter', [])),
            'submitter_tag': UserTag.objects.filter(id__in=session_data.get('submitter_tag', [])),
        }
        return result

    def create_or_update_deviation(self, submitter, exercise, module):
        exercise_id = exercise.id if exercise else None
        module_id = module.id if module else None
        existing_deviation = self.existing_deviations.get((submitter.id, exercise_id, module_id))
        if existing_deviation is not None:
            if (submitter.id, exercise_id, module_id) in self.override_deviations:
                existing_deviation.granter = self.request.user.userprofile
                existing_deviation.update_by_form(self.session_data)
                existing_deviation.save()
        else:
            new_deviation = self.deviation_model(
                exercise=exercise,
                module=module,
                submitter=submitter,
                granter=self.request.user.userprofile,
            )
            new_deviation.update_by_form(self.session_data)
            new_deviation.save()

class RemoveDeviationsByIDView(CourseInstanceMixin, BaseRedirectView):
    access_mode = ACCESS.TEACHER
    deviation_model: Type[SubmissionRuleDeviation]

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        deviations = self.deviation_model.objects.filter(
            Q(id__in=request.POST.getlist("id")), 
                Q(exercise__course_module__course_instance=self.instance)
                | Q(module__course_instance=self.instance)
        )
        for deviation in deviations:
            deviation.delete()
        if is_ajax(request):
            return HttpResponse(status=204)
        return self.redirect(self.deviation_model.get_list_url(self.instance))


class RemoveDeviationsView(CourseInstanceMixin, BaseFormView):
    access_mode = ACCESS.TEACHER
    deviation_model: Type[SubmissionRuleDeviation]

    def get_form_kwargs(self) -> Dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.instance
        return kwargs

    def get_success_url(self) -> str:
        return self.instance.get_url('deviations-remove-dl')

    def form_valid(self, form: forms.BaseForm) -> HttpResponse:
        number_of_removed = 0
        deviations = self.deviation_model.objects.filter(
            Q(submitter__in=get_submitters(form.cleaned_data)),
            Q(exercise__in=get_exercises(form.cleaned_data))
            | Q(module__in=form.cleaned_data['module'])
        )
        for deviation in deviations:
            deviation.delete()
            number_of_removed += 1
        if number_of_removed == 0:
            messages.warning(self.request, _("NOTHING_REMOVED"))
        else:
            message = ngettext(
                'REMOVED_DEVIATION -- {count}',
                'REMOVED_DEVIATIONS -- {count}',
                number_of_removed,
            ).format(count=number_of_removed)
            messages.info(self.request, message)
        return super().form_valid(form)


# pylint: disable-next=too-many-locals
def get_deviation_groups(
        all_deviations: models.QuerySet[SubmissionRuleDeviation],
        ) -> Iterable[Tuple[List[SubmissionRuleDeviation], bool, Optional[str]]]:
    """
    Group the deviations by user and module.

    Grouping condition: deviations can be grouped if the user has been
    granted the same deviation (based on the `is_equal` method) for all
    exercises in the module.

    The returned tuples contain the following values:
    1. List of deviations with the same user and module.
    2. Boolean representing whether the deviations in the list can be
    displayed as a group (i.e. the grouping condition is satisfied).
    3. An id that uniquely identifies the group of deviations.
    """
    # Find the number of exercises in each module.
    course_instances = (
        all_deviations
        .values_list('exercise__course_module__course_instance', flat=True)
        .distinct()
    )
    exercise_counts = (
        BaseExercise.objects.filter(
            course_module__course_instance__in=course_instances
        )
        .order_by()
        .values('course_module_id')
        .annotate(count=models.Count('*'))
    )
    exercise_count_by_module = {row['course_module_id']: row['count'] for row in exercise_counts}

    ordered_deviations = (
        all_deviations
        .select_related(
            'submitter', 'submitter__user',
            'granter', 'granter__user',
            'exercise', 'exercise__course_module',
            'exercise__course_module__course_instance',
        )
        .defer(
            'exercise__exercise_info',
            'exercise__description',
            'exercise__course_module__course_instance__description',
        )
        # parent is prefetched because there may be multiple ancestors, and
        # they are needed for building the deviation's URL.
        .prefetch_related('exercise__parent')
        .order_by('submitter', 'exercise__course_module')
    )

    deviation_groups = groupby(
        ordered_deviations,
        lambda obj: (obj.submitter, obj.exercise.course_module),
    )
    for (_submitter, module), deviations_iter in deviation_groups:
        deviations = list(deviations_iter)
        can_group = True
        show_granter = True
        if len(deviations) < 2:
            # Group must have at least 2 deviations.
            can_group = False
        else:
            group_exercises = set()
            # Check that the same deviation has been granted for all exercises.
            first_granter = deviations[0].granter.id
            for deviation in deviations:
                if not deviation.is_groupable(deviations[0]):
                    can_group = False
                    if not show_granter:
                        break
                if deviation.granter.id != first_granter:
                    show_granter = False
                    if not can_group:
                        break
                group_exercises.add(deviation.exercise.id)
            else:
                if len(group_exercises) != exercise_count_by_module[module.id]:
                    # The number of exercises that have deviations doesn't
                    # match the number of exercises in the module, so there
                    # are some exercises that don't have a deviation.
                    can_group = False
        group_id = f"{deviations[0].submitter.id}.{module.id}" if can_group else None
        yield (deviations, can_group, group_id, show_granter)


def get_exercises(form_data: Dict[str, Any]) -> models.QuerySet[BaseExercise]:
    """
    Get the exercises that match the input form's `exercise` and `module`
    fields.
    """
    return BaseExercise.objects.filter(
        models.Q(id__in=form_data.get('exercise', []))
        | models.Q(course_module__in=form_data.get('module', []))
    )


def get_submitters(form_data: Dict[str, Any]) -> models.QuerySet[UserProfile]:
    """
    Get the submitters that match the input form's `submitter` and
    `submitter_tag` fields.
    """
    return UserProfile.objects.filter(
        models.Q(id__in=form_data.get('submitter', []))
        | models.Q(taggings__tag__in=form_data.get('submitter_tag', []))
    ).distinct()


def new_deviation_seconds(
        deviation: DeadlineRuleDeviation,
        seconds: Optional[int],
        date: Optional[datetime.datetime]
        ) -> int:
    """
    Get the extra seconds for a deadline deviation after being overridden.
    """
    if date:
        return deviation.deviation_target.delta_in_seconds_from_closing_to_date(date)
    return seconds


def new_deviation_date(
        deviation: DeadlineRuleDeviation,
        seconds: Optional[int],
        date: Optional[datetime.datetime]
        ) -> datetime.datetime:
    """
    Get the new deadline for a deadline deviation after being overridden.
    """
    if date:
        return date
    module = deviation.module if deviation.module else deviation.exercise.course_module
    return module.closing_time + datetime.timedelta(seconds=seconds)
