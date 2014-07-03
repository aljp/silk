from django.core.context_processors import csrf
from django.db.models import Avg, Count, Sum, Max
from django.shortcuts import render_to_response
from django.utils.decorators import method_decorator
from django.views.generic import View

from silk import models
from silk.auth import login_possibly_required, permissions_possibly_required
from silk.request_filters import BaseFilter, filters_from_request


FILTERS_KEY = 'summary_filters'


class SummaryContextFactory(object):
    """
    Generate a context dictionary providing a summary of Silk's state.
    """
    def __init__(self, request):
        super(SummaryContextFactory, self).__init__()
        self.raw_filters = request.session.get(FILTERS_KEY, {})
        self.filters = [BaseFilter.from_dict(filter_d) for _, filter_d in self.raw_filters.items()]

    def get_context(self):
        """
        :return: dictionary to be used as context
        """
        pass


class DjangoSummaryContextFactory(SummaryContextFactory):
    def _avg_num_queries(self, filters):
        queries__aggregate = models.Request.objects.filter(*filters).annotate(num_queries=Count('queries')).aggregate(num=Avg('num_queries'))
        return queries__aggregate['num']

    def _avg_time_spent_on_queries(self, filters):
        taken__aggregate = models.Request.objects.filter(*filters).annotate(time_spent=Sum('queries__time_taken')).aggregate(num=Avg('time_spent'))
        return taken__aggregate['num']

    def _avg_overall_time(self, filters):
        taken__aggregate = models.Request.objects.filter(*filters).annotate(time_spent=Sum('time_taken')).aggregate(num=Avg('time_spent'))
        return taken__aggregate['num']

    # TODO: Find a more efficient way to do this. Currently has to go to DB num. views + 1 times and is prob quite expensive
    def _longest_query_by_view(self, filters):
        values_list = models.Request.objects.filter(*filters).values_list("view_name").annotate(max=Max('time_taken')).order_by('-max')[:6]
        requests = []
        for view_name, _ in values_list:
            request = models.Request.objects.filter(view_name=view_name, *filters).order_by('-time_taken')[0]
            requests.append(request)
        return requests

    def _time_spent_in_db_by_view(self, filters):
        values_list = models.Request.objects.filter(*filters).values_list('view_name').annotate(t=Sum('queries__time_taken')).order_by('-t')
        requests = []
        for view, _ in values_list:
            r = models.Request.objects.filter(view_name=view, *filters).annotate(t=Sum('queries__time_taken')).order_by('-t')[0]
            requests.append(r)
        return requests

    def _num_queries_by_view(self, filters):
        queryset = models.Request.objects.filter(*filters).values_list('view_name').annotate(t=Count('queries')).order_by('-t')
        views = [r[0] for r in queryset[:6]]
        requests = []
        for view in views:
            try:
                r = models.Request.objects.filter(view_name=view, *filters).annotate(t=Count('queries')).order_by('-t')[0]
                requests.append(r)
            except IndexError:
                pass
        return requests

    def get_context(self):
        """
        :return: dictionary to be used as context
        """
        avg_overall_time = self._avg_num_queries(self.filters)
        c = {
            'num_requests': models.Request.objects.filter(*self.filters).count(),
            'num_profiles': models.Profile.objects.filter(*self.filters).count(),
            'avg_num_queries': avg_overall_time,
            'avg_time_spent_on_queries': self._avg_time_spent_on_queries(self.filters),
            'avg_overall_time': self._avg_overall_time(self.filters),
            'longest_queries_by_view': self._longest_query_by_view(self.filters),
            'most_time_spent_in_db': self._time_spent_in_db_by_view(self.filters),
            'most_queries': self._num_queries_by_view(self.filters),
            'filters': self.raw_filters
        }
        return c


class ElasticsearchSummaryContextFactory(SummaryContextFactory):
    pass


class SummaryView(View):
    def _create_context(self, request):
        c = DjangoSummaryContextFactory(request).get_context()
        c['request'] = request
        c.update(csrf(request))
        return c

    @method_decorator(login_possibly_required)
    @method_decorator(permissions_possibly_required)
    def get(self, request):
        c = self._create_context(request)
        return render_to_response('silk/summary.html', c)


    @method_decorator(login_possibly_required)
    @method_decorator(permissions_possibly_required)
    def post(self, request):
        filters = filters_from_request(request)
        request.session[FILTERS_KEY] = {ident: f.as_dict() for ident, f in filters.items()}
        return render_to_response('silk/summary.html', self._create_context(request))