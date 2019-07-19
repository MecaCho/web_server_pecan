
import logging

from pecan import expose, redirect
from webob.exc import status_map

from pecan.rest import RestController
from books.book import BookController

LOG = logging.getLogger(__name__)


class V1Controller(RestController):
    books = None

    def __init__(self, user_id):
        super(V1Controller, self).__init__()
        self.books = BookController(user_id)


class RootController(object):

    @expose(generic=True, template='index.html')
    def index(self):
        return dict()

    def get_user(self, user_id):

        return True

    @index.when(method='POST')
    def index_post(self, q):
        redirect('https://pecan.readthedocs.io/en/latest/search.html?q=%s' % q)

    @index.when(method='GET')
    def index_get(self):
        return "hello world."

    @expose('error.html')
    def error(self, status):
        try:
            status = int(status)
        except ValueError:  # pragma: no cover
            status = 500
        message = getattr(status_map.get(status), 'explanation', '')
        return dict(status=status, message=message)

    @expose()
    def _lookup(self, user_id, *remainder):
        LOG.info(user_id)
        user_db = self.get_user(user_id)
        if user_db:
            return V1Controller(user_id), remainder
