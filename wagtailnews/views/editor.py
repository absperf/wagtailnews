from django.conf import settings
from django.contrib import messages
from django.core.handlers.base import BaseHandler
from django.core.handlers.wsgi import WSGIRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.lru_cache import lru_cache
from django.utils.six import StringIO
from django.utils.six.moves.urllib.parse import urlparse
from django.utils.translation import ugettext_lazy as _
from wagtail.wagtailadmin.edit_handlers import (
    ObjectList, extract_panel_definitions_from_model_class)
from wagtail.wagtailcore.models import Page

from ..forms import SaveActionSet
from ..models import get_newsindex_content_types


@lru_cache(maxsize=None)
def get_newsitem_edit_handler(NewsItem):
    panels = extract_panel_definitions_from_model_class(
        NewsItem, exclude=['newsindex'])
    return ObjectList(panels).bind_to_model(NewsItem)


def create(request, pk):
    newsindex = get_object_or_404(Page, pk=pk, content_type__in=get_newsindex_content_types()).specific
    NewsItem = newsindex.get_newsitem_model()

    newsitem = NewsItem(newsindex=newsindex)
    EditHandler = get_newsitem_edit_handler(NewsItem)
    EditForm = EditHandler.get_form_class(NewsItem)

    if request.method == 'POST':
        form = EditForm(request.POST, request.FILES, instance=newsitem)
        action = SaveActionSet.from_post_data(request.POST)

        if form.is_valid():
            newsitem = form.save(commit=False)
            newsitem.live = action is SaveActionSet.publish

            newsitem.save()
            newsitem.save_revision(user=request.user)

            if action is SaveActionSet.publish:
                messages.success(request, _('The news post "{0!s}" has been published').format(newsitem))
                return redirect('wagtailnews_index', pk=newsindex.pk)

            elif action is SaveActionSet.draft:
                messages.success(request, _('A draft news post "{0!s}" has been created').format(newsitem))
                return redirect('wagtailnews_edit', pk=newsindex.pk, newsitem_pk=newsitem.pk)

        else:
            messages.error(request, _('The news post could not be created due to validation errors'))
            edit_handler = EditHandler(instance=newsitem, form=form)
    else:
        form = EditForm(instance=newsitem)
        edit_handler = EditHandler(instance=newsitem, form=form)

    return render(request, 'wagtailnews/create.html', {
        'newsindex': newsindex,
        'form': form,
        'edit_handler': edit_handler,
    })


def edit(request, pk, newsitem_pk):
    newsindex = get_object_or_404(Page, pk=pk, content_type__in=get_newsindex_content_types()).specific
    NewsItem = newsindex.get_newsitem_model()
    newsitem = get_object_or_404(NewsItem, newsindex=newsindex, pk=newsitem_pk)
    newsitem = newsitem.get_latest_revision_as_newsitem()

    EditHandler = get_newsitem_edit_handler(NewsItem)
    EditForm = EditHandler.get_form_class(NewsItem)

    if request.method == 'POST':
        form = EditForm(request.POST, request.FILES, instance=newsitem)
        action = SaveActionSet.from_post_data(request.POST)

        if form.is_valid():
            newsitem = form.save(commit=False)
            revision = newsitem.save_revision(user=request.user)

            if action is SaveActionSet.publish:
                revision.publish()
                messages.success(request, _('Your changes to "{0!s}" have been published').format(newsitem))
                return redirect('wagtailnews_index', pk=newsindex.pk)

            elif action is SaveActionSet.draft:
                messages.success(request, _('Your changes to "{0!s}" have been saved as a draft').format(newsitem))
                return redirect('wagtailnews_edit', pk=newsindex.pk, newsitem_pk=newsitem.pk)

            elif action is SaveActionSet.preview:
                return redirect('wagtailnews_view_draft', pk=newsindex.pk, newsitem_pk=newsitem.pk)
        else:
            messages.error(request, _('The news post could not be updated due to validation errors'))
            edit_handler = EditHandler(instance=newsitem, form=form)
    else:
        form = EditForm(instance=newsitem)
        edit_handler = EditHandler(instance=newsitem, form=form)

    return render(request, 'wagtailnews/edit.html', {
        'newsindex': newsindex,
        'newsitem': newsitem,
        'form': form,
        'edit_handler': edit_handler,
    })


def delete(request, pk, newsitem_pk):
    newsindex = get_object_or_404(Page, pk=pk, content_type__in=get_newsindex_content_types()).specific
    NewsItem = newsindex.get_newsitem_model()
    newsitem = get_object_or_404(NewsItem, newsindex=newsindex, pk=newsitem_pk)

    if request.method == 'POST':
        newsitem.delete()
        return redirect('wagtailnews_index', pk=pk)

    return render(request, 'wagtailnews/delete.html', {
        'newsindex': newsindex,
        'newsitem': newsitem,
    })


def view_draft(request, pk, newsitem_pk):
    newsindex = get_object_or_404(Page, pk=pk, content_type__in=get_newsindex_content_types()).specific
    NewsItem = newsindex.get_newsitem_model()
    newsitem = get_object_or_404(NewsItem, newsindex=newsindex, pk=newsitem_pk)
    newsitem = newsitem.get_latest_revision_as_newsitem()

    dummy_request = build_dummy_request(newsitem)
    template = newsitem.get_template(dummy_request)
    context = newsitem.get_context(
        dummy_request, year=newsitem.date.year, month=newsitem.date.month,
        day=newsitem.date.day, pk=newsitem.pk, slug=newsitem.get_nice_url())
    return render(dummy_request, template, context)


def build_dummy_request(newsitem):
    """
    Construct a HttpRequest object that is, as far as possible,
    representative of ones that would receive this page as a response. Used
    for previewing / moderation and any other place where we want to
    display a view of this page in the admin interface without going
    through the regular page routing logic.
    """
    url = newsitem.full_url()
    if url:
        url_info = urlparse(url)
        hostname = url_info.hostname
        path = url_info.path
        port = url_info.port or 80
    else:
        # Cannot determine a URL to this page - cobble one together based on
        # whatever we find in ALLOWED_HOSTS
        try:
            hostname = settings.ALLOWED_HOSTS[0]
        except IndexError:
            hostname = 'localhost'
        path = '/'
        port = 80

    request = WSGIRequest({
        'REQUEST_METHOD': 'GET',
        'PATH_INFO': path,
        'SERVER_NAME': hostname,
        'SERVER_PORT': port,
        'HTTP_HOST': hostname,
        'wsgi.input': StringIO(),
    })

    # Apply middleware to the request - see http://www.mellowmorning.com/2011/04/18/mock-django-request-for-testing/
    handler = BaseHandler()
    handler.load_middleware()
    # call each middleware in turn and throw away any responses that they might return
    for middleware_method in handler._request_middleware:
        middleware_method(request)

    return request
