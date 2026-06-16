# View functions backing the Usage Cost Dashboard admin pages.
# Registered as custom admin URLs in UsageCostLogAdmin.get_urls() rather than
# as standalone URL patterns so they inherit admin authentication and jazzmin context.
from django.contrib import admin
from django.core.paginator import Paginator
from django.db.models import Sum
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
import datetime

from chatbot.models import ChatSession, UsageCostLog

SESSION_COST_CHART_PAGE_SIZE = 100


# Purpose: Builds context for the "Sessions and Cost" table.
# Inputs:  request — GET params: session_view (top1|top10|all), q (search), page.
# Output:  Dict with top_sessions, sessions_page, session_view, search_query.
def _get_sessions_context(request):
    search_query = request.GET.get('q', '').strip()
    session_view = request.GET.get('session_view', 'top10')
    if session_view not in ('top1', 'top10', 'all'):
        session_view = 'top10'
    if search_query:
        session_view = 'all'

    # Exclude zero-cost sessions (test/system calls) to keep the dashboard focused on real spend.
    sessions_qs = ChatSession.objects.filter(total_cost__gt=0).order_by('-total_cost')
    if search_query:
        sessions_qs = sessions_qs.filter(session__icontains=search_query)

    sessions_page = None
    if session_view == 'top1':
        top_sessions = sessions_qs[:1]
    elif session_view == 'all':
        paginator = Paginator(sessions_qs, 20)
        sessions_page = paginator.get_page(request.GET.get('page'))
        top_sessions = sessions_page
    else:
        top_sessions = sessions_qs[:10]

    return {
        'top_sessions': top_sessions,
        'sessions_page': sessions_page,
        'session_view': session_view,
        'search_query': search_query,
    }


# Purpose: Returns paginated session cost data for the "Cost by Session" bar chart.
# Inputs:  request    — GET params read via page_param for current page number.
#          page_param — Query param name to read the page number from.
# Output:  Dict with labels (session IDs), values (costs), page, num_pages.
def _get_session_cost_chart_data(request, page_param='page'):
    sessions_qs = ChatSession.objects.filter(total_cost__gt=0).order_by('-created_at')
    paginator = Paginator(sessions_qs, SESSION_COST_CHART_PAGE_SIZE)
    page = paginator.get_page(request.GET.get(page_param))

    return {
        'labels': [s.session for s in page.object_list],
        'values': [float(s.total_cost) for s in page.object_list],
        'page': page.number,
        'num_pages': paginator.num_pages,
    }


# Purpose: JSON endpoint for "Cost by Session" bar chart page navigation.
# Inputs:  request — GET param: page.
# Output:  JSON: {labels, values, page, num_pages}.
def usage_cost_session_chart(request):
    return JsonResponse(_get_session_cost_chart_data(request))


# Purpose: Renders the "Sessions and Cost" table partial for AJAX refreshes.
#          Returns only the table fragment so filter/search/pagination updates
#          don't trigger a full page reload (avoids re-rendering all charts).
# Inputs:  request — GET params: session_view, q, page.
# Output:  Rendered HTML fragment (usage_cost_sessions_table.html).
def usage_cost_sessions_partial(request):
    context = {
        **admin.site.each_context(request),
        **_get_sessions_context(request),
    }
    return render(request, 'admin/usage_cost_sessions_table.html', context)


# Purpose:      Renders the full cost monitoring dashboard.
# Inputs:       request — GET params: session_view, q, page, chart_page.
# Output:       Rendered dashboard page with five aggregated datasets:
#               daily cost trend (30 days), cost by call type, cost by provider,
#               cost by bot (top 20), and paginated session cost chart data.
# Side effects: None (read-only).
# Note:         admin.site.each_context injects jazzmin sidebar/nav/permission context.
def usage_cost_dashboard(request):
    since = timezone.now() - datetime.timedelta(days=30)

    by_call_type = (
        UsageCostLog.objects.values('call_type')
        .annotate(total=Sum('total_cost'))
        .order_by('-total')
    )

    by_provider = (
        UsageCostLog.objects.values('provider')
        .annotate(total=Sum('total_cost'))
        .order_by('-total')
    )

    by_company_bot = (
        UsageCostLog.objects.values('company_bot__name')
        .annotate(total=Sum('total_cost'))
        .order_by('-total')[:20]
    )

    daily_trend = (
        UsageCostLog.objects.filter(created_at__gte=since)
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(total=Sum('total_cost'))
        .order_by('day')
    )

    session_cost_chart = _get_session_cost_chart_data(request, page_param='chart_page')

    context = {
        **admin.site.each_context(request),
        'title': 'Cost Monitoring Dashboard',
        **_get_sessions_context(request),
        'by_call_type': list(by_call_type),
        'by_provider': list(by_provider),
        'by_company_bot': list(by_company_bot),
        'daily_trend_labels': [d['day'].isoformat() for d in daily_trend],
        'daily_trend_values': [float(d['total'] or 0) for d in daily_trend],
        'session_cost_chart_labels': session_cost_chart['labels'],
        'session_cost_chart_values': session_cost_chart['values'],
        'session_cost_chart_page': session_cost_chart['page'],
        'session_cost_chart_num_pages': session_cost_chart['num_pages'],
    }
    return render(request, 'admin/usage_cost_dashboard.html', context)


# Purpose: Renders a per-session cost breakdown page.
# Inputs:  request    — HTTP request (admin auth required).
#          session_pk — Primary key of the ChatSession to inspect.
# Output:  Rendered page listing every UsageCostLog row for the session,
#          ordered chronologically, with session summary metadata.
def usage_cost_session_detail(request, session_pk):
    chat_session = ChatSession.objects.filter(pk=session_pk).first()
    logs = UsageCostLog.objects.filter(session_id=session_pk).order_by('created_at')

    context = {
        **admin.site.each_context(request),
        'title': 'Session Cost Breakdown',
        'chat_session': chat_session,
        'logs': logs,
    }
    return render(request, 'admin/usage_cost_session_detail.html', context)
