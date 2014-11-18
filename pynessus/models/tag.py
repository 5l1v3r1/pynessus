__author__ = 'Quentin Kaiser'
__license__ = "Apache 2.0"
__version__ = "0.1"
__contact__ = "kaiserquentin@gmail.com"
__date__ = "2014/16/11"


class Tag(object):
    """
    A Nessus Tag instance.

    Attributes:

    _Google Python Style Guide:
    http://google-styleguide.googlecode.com/svn/trunk/pyguide.html
    """

    def __init__(self):
        """Constructor"""
        self._id = -1
        self._default_tag = 1
        self._type = None
        self._name = None
        self._custom = False
        self._unread_count = 0

    @property
    def id(self):
        return self._id

    @id.setter
    def id(self, _id):
        self._id = _id

    @property
    def default_tag(self):
        return self._default_tag

    @default_tag.setter
    def default_tag(self, default_tag):
        self._default_tag = default_tag

    @property
    def type(self):
        return self._type

    @type.setter
    def type(self, _type):
        self._type = _type

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, name):
        self._name = name

    @property
    def custom(self):
        return self._custom

    @custom.setter
    def custom(self, custom):
        self._custom = custom

    @property
    def unread_count(self):
        return self._unread_count

    @unread_count.setter
    def unread_count(self, unread_count):
        self._unread_count = unread_count
