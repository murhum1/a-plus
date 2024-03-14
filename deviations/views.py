from typing import Any, Callable, Dict, Optional
import datetime

from django.utils.dateparse import parse_datetime

from .forms import (
    DeadlineRuleDeviationForm,
    RemoveDeviationForm,
    MaxSubmissionRuleDeviationForm,
)
from .viewbase import (
    AddDeviationsView,
    ListDeviationsView,
    OverrideDeviationsView,
    RemoveDeviationsByIDView,
    RemoveDeviationsView,
)
from .models import DeadlineRuleDeviation, MaxSubmissionsRuleDeviation


class ListDeadlinesView(ListDeviationsView):
    template_name = "deviations/list_dl.html"
    deviation_model = DeadlineRuleDeviation


class AddDeadlinesView(AddDeviationsView):
    template_name = "deviations/add_dl.html"
    form_class = DeadlineRuleDeviationForm
    deviation_model = DeadlineRuleDeviation
    session_key = 'add-deviations-data-dl'

    def get_success_no_override_url(self) -> str:
        return self.instance.get_url('deviations-add-dl')

    def get_initial_get_param_spec(self) -> Dict[str, Optional[Callable[[str], Any]]]:
        spec = super().get_initial_get_param_spec()
        spec.update({
            "seconds": int,
            "new_date": None,
            "without_late_penalty": lambda x: x == "true",
        })
        return spec

    def serialize_session_data(self, form_data: Dict[str, Any]) -> Dict[str, Any]:
        result = super().serialize_session_data(form_data)
        result.update({
            'seconds': form_data['seconds'],
            'new_date': str(form_data['new_date']) if form_data['new_date'] else None,
            'without_late_penalty': form_data['without_late_penalty'],
        })
        return result


class OverrideDeadlinesView(OverrideDeviationsView):
    template_name = "deviations/override_dl.html"
    deviation_model = DeadlineRuleDeviation
    session_key = 'add-deviations-data-dl'

    def get_common_objects(self) -> None:
        super().get_common_objects()
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
        self.node("new_deviation_seconds", "new_deviation_date")

    def get_success_url(self) -> str:
        return self.instance.get_url('deviations-add-dl')

    def deserialize_session_data(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        result = super().deserialize_session_data(session_data)
        result.update({
            'seconds': session_data['seconds'],
            'new_date': parse_datetime(session_data['new_date']) if session_data['new_date'] else None,
            'without_late_penalty': session_data['without_late_penalty'],
        })
        return result


class RemoveDeadlinesByIDView(RemoveDeviationsByIDView):
    deviation_model = DeadlineRuleDeviation


class RemoveDeadlinesView(RemoveDeviationsView):
    template_name = "deviations/remove_dl.html"
    form_class = RemoveDeviationForm
    deviation_model = DeadlineRuleDeviation


class ListSubmissionsView(ListDeviationsView):
    template_name = "deviations/list_submissions.html"
    deviation_model = MaxSubmissionsRuleDeviation


class AddSubmissionsView(AddDeviationsView):
    template_name = "deviations/add_submissions.html"
    form_class = MaxSubmissionRuleDeviationForm
    deviation_model = MaxSubmissionsRuleDeviation
    session_key = 'add-deviations-data-submissions'

    def get_success_no_override_url(self) -> str:
        return self.instance.get_url('deviations-add-submissions')

    def serialize_session_data(self, form_data: Dict[str, Any]) -> Dict[str, Any]:
        result = super().serialize_session_data(form_data)
        result['extra_submissions'] = form_data['extra_submissions']
        return result


class OverrideSubmissionsView(OverrideDeviationsView):
    template_name = "deviations/override_submissions.html"
    deviation_model = MaxSubmissionsRuleDeviation
    session_key = 'add-deviations-data-submissions'

    def get_success_url(self) -> str:
        return self.instance.get_url('deviations-add-submissions')

    def deserialize_session_data(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        result = super().deserialize_session_data(session_data)
        result['extra_submissions'] = session_data['extra_submissions']
        return result


class RemoveSubmissionsByIDView(RemoveDeviationsByIDView):
    deviation_model = MaxSubmissionsRuleDeviation


class RemoveSubmissionsView(RemoveDeviationsView):
    template_name = "deviations/remove_submissions.html"
    form_class = RemoveDeviationForm
    deviation_model = MaxSubmissionsRuleDeviation

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
