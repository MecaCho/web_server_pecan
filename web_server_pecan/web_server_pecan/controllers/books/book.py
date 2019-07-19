from pecan import expose
from pecan.rest import RestController
import logging

LOG = logging.getLogger(__name__)


class BookController(RestController):

    def __init__(self, user_id):
        LOG.info("book controller.")
        self.user_id = user_id

    @expose()
    def get(self, book_id):
        return "This is a book , user_id : {}, book_id: {}.".format(self.user_id, book_id)

    @expose()
    def get_all(self):
        return "Get all books , user_id : {}, book_list.".format(self.user_id)

    @expose()
    def get_one(self, book_id):
        return "Get one book, book_id: {}".format(book_id)

    @expose()
    def put(self, body):
        return "Put new book, body: {}.".format(str(body))

    @expose()
    def delete(self, book_id):
        return "Delete a book, book_id: {}".format(book_id)

    @expose()
    def post(self):
        return "Create a book , user_id : {}.".format(self.user_id)
