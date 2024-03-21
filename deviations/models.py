from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Dict, Generic, Iterable, Optional, TypeVar, Union
from operator import attrgetter

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from course.models import CourseInstance, CourseModule
from exercise.exercise_models import BaseExercise
from exercise.submission_models import Submission
from userprofile.models import UserProfile
from lib.fields import DefaultForeignKey
from lib.models import UrlMixin

TModel = TypeVar('TModel', bound='SubmissionRuleDeviation')
class SubmissionRuleDeviationManager(models.Manager[TModel], Generic[TModel]):
    max_order_by: str

    def get_max_deviations(
        self,
        submitter: UserProfile,
        exercises: Iterable[Union[BaseExercise, int]],
    ) -> Dict[int, TModel]:
        """
        Returns the maximum deviations for the given submitter in the given
        exercises (one deviation per exercise is returned). The deviation may
        be granted to the submitter directly, or to some other submitter in
        their group.
        """
        exercises = [e if isinstance(e, int) else e.id for e in exercises]
        modules = CourseModule.objects.filter(learning_objects__in=exercises)
        deviations_self = (
            self.filter(
                Q(exercise__in=exercises) | Q(module__in=modules),
                submitter=submitter,
            )
            .select_related('exercise', 'module')
        )
        deviations_group = (
            self.filter(
                ( models.Q(exercise__in=exercises) | models.Q(module__in=modules) )
                & ~models.Q(submitter=submitter)
                & (
                    # Check that the owner of the deviation is
                    # some other user who has submitted the deviation's
                    # exercise with the user.
                    models.Exists(
                        # Note the two 'submitters' filters.
                        Submission.objects.filter(
                            Q(exercise=models.OuterRef('exercise')) | Q(exercise__course_module=models.OuterRef('module')),
                            submitters=models.OuterRef('submitter'),
                        ).filter(
                            submitters=submitter,
                        )
                    )
                )
            )
            .select_related('exercise', 'module')
        )

        deviations = (
            deviations_self
            .union(deviations_group)
            #.order_by('exercise', 'module', self.max_order_by)
        )
        max_deviations = {}
        # pick the largest out of personal / group / module / exercise deviations
        for deviation in deviations:
            if deviation.module:
                exercise_dicts = BaseExercise.objects.filter(id__in=exercises, course_module=deviation.module).values('id')
                for d in exercise_dicts:
                    max_deviations[d['id']] = self.get_bigger_deviation(deviation, max_deviations.get(d['id']))
            if deviation.exercise:
                d_id = deviation.exercise.id
                max_deviations[d_id] = self.get_bigger_deviation(deviation, max_deviations.get(d_id))
        return max_deviations
    
    def get_bigger_deviation(self, dev1: TModel, dev2: TModel):
        if not dev2:
            return dev1
        if not dev1:
            return dev2
        if self.max_order_by[0] == '-':
            return max(dev1, dev2, key=attrgetter(self.max_order_by[1:]))
        else:
            return min(dev1, dev2, key=attrgetter(self.max_order_by))

    def get_max_deviation(self, submitter: UserProfile, exercise: Union[BaseExercise, int]) -> Optional[TModel]:
        """
        Returns the maximum deviation for the given submitter in the given
        exercise. The deviation may be granted to the submitter directly, or to
        some other submitter in their group.
        """
        deviations = self.get_max_deviations(submitter, [exercise])
        return deviations.get(exercise.id)


class SubmissionRuleDeviation(UrlMixin, models.Model):
    """
    An abstract model binding a user to an exercise stating that there is some
    kind of deviation from the normal submission boundaries, that is, special
    treatment related to the submissions of that particular user to that
    particular exercise.

    If there are many submitters submitting an exercise out of bounds of the
    default bounds, all of the submitters must have an allowing instance of
    SubmissionRuleDeviation subclass in order for the submission to be allowed.
    """
    exercise = DefaultForeignKey(BaseExercise,
        verbose_name=_('LABEL_EXERCISE'),
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )
    module = DefaultForeignKey(CourseModule,
        verbose_name=_('LABEL_MODULE'),
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )
    submitter = models.ForeignKey(UserProfile,
        verbose_name=_('LABEL_SUBMITTER'),
        on_delete=models.CASCADE,
    )
    granter = models.ForeignKey(UserProfile,
        verbose_name=_('LABEL_GRANTER'),
        on_delete=models.SET_NULL,
        related_name='+',
        blank=True,
        null=True,
    )
    grant_time = models.DateTimeField(
        verbose_name=_('LABEL_GRANT_TIME'),
        auto_now=True,
        blank=True,
        null=True,
    )

    if TYPE_CHECKING:
        id: models.AutoField

    class Meta:
        verbose_name = _('MODEL_NAME_SUBMISSION_RULE_DEVIATION')
        verbose_name_plural = _('MODEL_NAME_SUBMISSION_RULE_DEVIATION_PLURAL')
        abstract = True
        unique_together = ["exercise", "submitter"]
        constraints = [
            models.CheckConstraint(
                name="%(class)s_require_exercise_or_module",
                check=(
                    models.Q(exercise__isnull=True, module__isnull=False) |
                    models.Q(exercise__isnull=False, module__isnull=True)
                )
            )
        ]

    def get_url_kwargs(self):
        # pylint: disable-next=use-dict-literal
        return dict(deviation_id=self.id, **self.deviation_target.course_instance.get_url_kwargs())

    def update_by_form(self, form_data: Dict[str, Any]) -> None:
        """
        Update the deviation's attributes based on a provided set of form
        values.
        """
        raise NotImplementedError()

    def is_groupable(self, other: 'SubmissionRuleDeviation') -> bool:
        """
        Whether this deviation can be grouped with another deviation in tables.
        """
        raise NotImplementedError()
    
    @property
    def deviation_target(self):
        return self.exercise or self.module

    @classmethod
    def get_list_url(cls, instance: CourseInstance) -> str:
        """
        Get the URL of the deviation list page for deviations of this type.
        """
        raise NotImplementedError()

    @classmethod
    def get_override_url(cls, instance: CourseInstance) -> str:
        """
        Get the URL of the deviation override page for deviations of this type.
        """
        raise NotImplementedError()


class DeadlineRuleDeviationManager(SubmissionRuleDeviationManager['DeadlineRuleDeviation']):
    max_order_by = "-extra_seconds"


class DeadlineRuleDeviation(SubmissionRuleDeviation):
    extra_seconds = models.IntegerField(
        verbose_name=_('LABEL_EXTRA_SECONDS'),
    )
    without_late_penalty = models.BooleanField(
        verbose_name=_('LABEL_WITHOUT_LATE_PENALTY'),
        default=True,
    )

    objects = DeadlineRuleDeviationManager()

    class Meta(SubmissionRuleDeviation.Meta):
        verbose_name = _('MODEL_NAME_DEADLINE_RULE_DEVIATION')
        verbose_name_plural = _('MODEL_NAME_DEADLINE_RULE_DEVIATION_PLURAL')

    def get_extra_time(self):
        return timedelta(seconds=self.extra_seconds)

    def get_new_deadline(self, normal_deadline: Optional[datetime] = None) -> datetime:
        """
        Returns the new deadline after adding the extra time to the normal
        deadline.

        The `normal_deadline` argument can be provided if it is known by the
        caller, to avoid querying it.
        """
        if normal_deadline is None:
            normal_deadline = self.get_normal_deadline()
        return normal_deadline + self.get_extra_time()

    def get_normal_deadline(self):
        module = self.module if self.module else self.exercise.course_module
        return module.closing_time

    def update_by_form(self, form_data: Dict[str, Any]) -> None:
        seconds = form_data.get('seconds')
        new_date = form_data.get('new_date')
        if new_date:
            seconds = self.exercise.delta_in_seconds_from_closing_to_date(new_date)
        else:
            seconds = int(seconds)
        self.extra_seconds = seconds
        self.without_late_penalty = bool(form_data.get('without_late_penalty'))

    def is_groupable(self, other: 'DeadlineRuleDeviation') -> bool:
        return (
            self.exercise
            and self.extra_seconds == other.extra_seconds
            and self.without_late_penalty == other.without_late_penalty
        )

    @classmethod
    def get_list_url(cls, instance: CourseInstance) -> str:
        return instance.get_url('deviations-list-dl')

    @classmethod
    def get_override_url(cls, instance: CourseInstance) -> str:
        return instance.get_url('deviations-override-dl')


class MaxSubmissionsRuleDeviationManager(SubmissionRuleDeviationManager['MaxSubmissionsRuleDeviation']):
    max_order_by = "-extra_submissions"


class MaxSubmissionsRuleDeviation(SubmissionRuleDeviation):
    extra_submissions = models.IntegerField(
        verbose_name=_('LABEL_EXTRA_SUBMISSIONS'),
    )

    objects = MaxSubmissionsRuleDeviationManager()

    class Meta(SubmissionRuleDeviation.Meta):
        verbose_name = _('MODEL_NAME_MAX_SUBMISSIONS_RULE_DEVIATION')
        verbose_name_plural = _('MODEL_NAME_MAX_SUBMISSIONS_RULE_DEVIATION_PLURAL')

    def update_by_form(self, form_data: Dict[str, Any]) -> None:
        self.extra_submissions = int(form_data['extra_submissions'])

    def is_groupable(self, other: 'MaxSubmissionsRuleDeviation') -> bool:
        return self.extra_submissions == other.extra_submissions

    @classmethod
    def get_list_url(cls, instance: CourseInstance) -> str:
        return instance.get_url('deviations-list-submissions')

    @classmethod
    def get_override_url(cls, instance: CourseInstance) -> str:
        return instance.get_url('deviations-override-submissions')
