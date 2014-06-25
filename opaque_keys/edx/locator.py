"""
Identifier for course resources.
"""

from __future__ import absolute_import
import logging
import inspect
import re
import warnings
from bson.son import SON
from abc import abstractmethod

from bson.objectid import ObjectId
from bson.errors import InvalidId

from opaque_keys import OpaqueKey, InvalidKeyError

from opaque_keys.edx.keys import CourseKey, UsageKey, DefinitionKey, AssetKey

log = logging.getLogger(__name__)


class LocalId(object):
    """
    Class for local ids for non-persisted xblocks (which can have hardcoded block_ids if necessary)
    """
    def __init__(self, block_id=None):
        self.block_id = block_id
        super(LocalId, self).__init__()

    def __str__(self):
        return "localid_{}".format(self.block_id or id(self))


class Locator(OpaqueKey):
    """
    A locator identifies a course resource.

    Locator is an abstract base class: do not instantiate
    """

    BLOCK_TYPE_PREFIX = r"type"
    # Prefix for the version portion of a locator URL, when it is preceded by a course ID
    VERSION_PREFIX = r"version"
    ALLOWED_ID_CHARS = r'[\w\-~.:]'
    DEPRECATED_ALLOWED_ID_CHARS = r'[\w\-~.:%]'

    def __str__(self):
        """
        str(self) returns something like this: "mit.eecs.6002x"
        """
        return unicode(self).encode('utf-8')

    @abstractmethod
    def version(self):  # pragma: no cover
        """
        Returns the ObjectId referencing this specific location.

        Raises:
            InvalidKeyError: if the instance doesn't have a complete enough specification.
        """
        raise NotImplementedError()

    @classmethod
    def as_object_id(cls, value):
        """
        Attempts to cast value as a bson.objectid.ObjectId.

        Raises:
            ValueError: if casting fails
        """
        try:
            return ObjectId(value)
        except InvalidId:
            raise ValueError('"%s" is not a valid version_guid' % value)


# `BlockLocatorBase` is another abstract base class, so don't worry that it doesn't
# provide implementations for _from_string, _to_string, and version.
# pylint: disable=abstract-method
class BlockLocatorBase(Locator):
    """
    Abstract base clase for XBlock locators.

    See subclasses for more detail, particularly `CourseLocator` and `BlockUsageLocator`.
    """
    # Token separating org from offering
    ORG_SEPARATOR = '+'

    # Prefix for the branch portion of a locator URL
    BRANCH_PREFIX = r"branch"
    # Prefix for the block portion of a locator URL
    BLOCK_PREFIX = r"block"

    ALLOWED_ID_RE = re.compile(r'^' + Locator.ALLOWED_ID_CHARS + '+$', re.UNICODE)
    DEPRECATED_ALLOWED_ID_RE = re.compile(r'^' + Locator.DEPRECATED_ALLOWED_ID_CHARS + '+$', re.UNICODE)

    # pep8 and pylint don't agree on the indentation in this block; let's make
    # pep8 happy and ignore pylint as that's easier to do.
    # pylint: disable=bad-continuation
    URL_RE_SOURCE = r"""
        ((?P<org>{ALLOWED_ID_CHARS}+)\+(?P<course>{ALLOWED_ID_CHARS}+)\+(?P<run>{ALLOWED_ID_CHARS}+)\+?)??
        ({BRANCH_PREFIX}\+(?P<branch>{ALLOWED_ID_CHARS}+)\+?)?
        ({VERSION_PREFIX}\+(?P<version_guid>[A-F0-9]+)\+?)?
        ({BLOCK_TYPE_PREFIX}\+(?P<block_type>{ALLOWED_ID_CHARS}+)\+?)?
        ({BLOCK_PREFIX}\+(?P<block_id>{ALLOWED_ID_CHARS}+))?
        """.format(
        ALLOWED_ID_CHARS=Locator.ALLOWED_ID_CHARS,
        BRANCH_PREFIX=BRANCH_PREFIX,
        VERSION_PREFIX=Locator.VERSION_PREFIX,
        BLOCK_TYPE_PREFIX=Locator.BLOCK_TYPE_PREFIX,
        BLOCK_PREFIX=BLOCK_PREFIX,
    )

    URL_RE = re.compile('^' + URL_RE_SOURCE + '$', re.IGNORECASE | re.VERBOSE | re.UNICODE)

    @classmethod
    def parse_url(cls, string):
        """
        If it can be parsed as a version_guid with no preceding org + offering, returns a dict
        with key 'version_guid' and the value,

        If it can be parsed as a org + offering, returns a dict
        with key 'id' and optional keys 'branch' and 'version_guid'.

        Raises:
            InvalidKeyError: if string cannot be parsed.
        """
        match = cls.URL_RE.match(string)
        if not match:
            raise InvalidKeyError(cls, string)
        return match.groupdict()

    @property
    def package_id(self):
        """
        Returns the package identifier for this `BlockLocator`.

        Returns 'self.org+self.course+self.run' if both are present; else returns None.
        """
        if self.org and self.course and self.run:
            # will there ever be a case where we want ORG_SEPARATOR and COURSE_SEPARATOR to be different?
            # if no, we should combine them
            return self.ORG_SEPARATOR.join([self.org, self.course, self.run])
        else:
            return None
# pylint: enable=abstract-method


class CourseLocator(BlockLocatorBase, CourseKey):
    """
    Examples of valid CourseLocator specifications:
     CourseLocator(version_guid=ObjectId('519665f6223ebd6980884f2b'))
     CourseLocator(org='mit.eecs', course='6.002x', run='T2_2014')
     CourseLocator(org='mit.eecs', course='6002x', run='fall_2014' branch = 'published')
     CourseLocator.from_string('course-locator:version+519665f6223ebd6980884f2b')
     CourseLocator.from_string('course-locator:mit.eecs+6002x')
     CourseLocator.from_string('course-locator:mit.eecs+6002x+branch+published')
     CourseLocator.from_string('course-locator:mit.eecs+6002x+branch+published+version+519665f6223ebd6980884f2b')

    Should have at least a specific org, course, and run with optional 'branch',
    or version_guid (which points to a specific version). Can contain both in which case
    the persistence layer may raise exceptions if the given version != the current such version
    of the course.
    """
    CANONICAL_NAMESPACE = 'course-locator'
    KEY_FIELDS = ('org', 'course', 'run', 'branch', 'version_guid')
    __slots__ = KEY_FIELDS

    # Characters that are forbidden in the deprecated format
    INVALID_CHARS_DEPRECATED = re.compile(r"[^\w.%-]", re.UNICODE)

    # stubs to fake out the abstractproperty class instrospection and allow treatment as attrs in instances
    org = None

    def __init__(self, org=None, course=None, run=None, branch=None, version_guid=None, deprecated=False, **kwargs):
        """
        Construct a CourseLocator

        Args:
            version_guid (string or ObjectId): optional unique id for the version
            org, course, run (string): the standard definition. Optional only if version_guid given
            branch (string): the branch such as 'draft', 'published', 'staged', 'beta'
        """
        if deprecated:
            for part in (org, course, run):
                self._check_location_part(part, self.INVALID_CHARS_DEPRECATED)

            fields = [org, course]
            # Deprecated style allowed to have None for run and branch
            if run is not None:
                fields.append(run)
            if branch is not None:
                fields.append(branch)
            if not all(self.DEPRECATED_ALLOWED_ID_RE.match(field) for field in fields):
                raise InvalidKeyError(self.__class__, fields)

        else:
            if version_guid:
                version_guid = self.as_object_id(version_guid)

            if not all(field is None or self.ALLOWED_ID_RE.match(field) for field in [org, course, run, branch]):
                raise InvalidKeyError(self.__class__, [org, course, run, branch])

        super(CourseLocator, self).__init__(
            org=org,
            course=course,
            run=run,
            branch=branch,
            version_guid=version_guid,
            deprecated=deprecated,
            **kwargs
        )

        if self.deprecated and (self.org is None or self.course is None):
            raise InvalidKeyError(self.__class__, "Deprecated strings must set both org and course.")

        if not self.deprecated and self.version_guid is None and (self.org is None or self.course is None or self.run is None):
            raise InvalidKeyError(self.__class__, "Either version_guid or org, course, and run should be set")

    @classmethod
    def _check_location_part(cls, val, regexp):
        if val is None:
            return
        if not isinstance(val, basestring):
            raise InvalidKeyError(cls, "{!r} is not a string".format(val))
        if regexp.search(val) is not None:
            raise InvalidKeyError(cls, "Invalid characters in {!r}.".format(val))

    def version(self):
        """
        Returns the ObjectId referencing this specific location.
        """
        return self.version_guid

    @classmethod
    def _from_string(cls, serialized):
        """
        Return a CourseLocator parsing the given serialized string
        :param serialized: matches the string to a CourseLocator
        """
        parse = cls.parse_url(serialized)

        if parse['version_guid']:
            parse['version_guid'] = cls.as_object_id(parse['version_guid'])

        return cls(**{key: parse.get(key) for key in cls.KEY_FIELDS})

    def html_id(self):
        """
        Generate a discussion group id based on course

        To make compatible with old Location object functionality. I don't believe this behavior fits at this
        place, but I have no way to override. We should clearly define the purpose and restrictions of this
        (e.g., I'm assuming periods are fine).
        """
        return unicode(self)

    def make_usage_key(self, block_type, block_id):
        return BlockUsageLocator(
            course_key=self,
            block_type=block_type,
            block_id=block_id,
            deprecated=self.deprecated,
        )

    def make_asset_key(self, asset_type, path):
        return AssetLocator(self, asset_type, path, deprecated=self.deprecated)

    def version_agnostic(self):
        """
        We don't care if the locator's version is not the current head; so, avoid version conflict
        by reducing info.
        Returns a copy of itself without any version info.

        Raises:
            ValueError: if the block locator has no org & course, run
        """
        return CourseLocator(
            org=self.org,
            course=self.course,
            run=self.run,
            branch=self.branch,
            version_guid=None
        )

    def course_agnostic(self):
        """
        We only care about the locator's version not its course.
        Returns a copy of itself without any course info.

        Raises:
            ValueError: if the block locator has no version_guid
        """
        return CourseLocator(
            org=None,
            course=None,
            run=None,
            branch=None,
            version_guid=self.version_guid
        )

    def for_branch(self, branch):
        """
        Return a new CourseLocator for another branch of the same course (also version agnostic)
        """
        if self.org is None:
            raise InvalidKeyError(self.__class__, "Branches must have full course ids not just versions")
        return CourseLocator(
            org=self.org,
            course=self.course,
            run=self.run,
            branch=branch,
            version_guid=None
        )

    def for_version(self, version_guid):
        """
        Return a new CourseLocator for another version of the same course and branch. Usually used
        when the head is updated (and thus the course x branch now points to this version)
        """
        return CourseLocator(
            org=self.org,
            course=self.course,
            run=self.run,
            branch=self.branch,
            version_guid=version_guid
        )

    def _to_string(self):
        """
        Return a string representing this location.
        """
        parts = []
        if self.course and self.run:
            parts.append(unicode(self.package_id))
            if self.branch:
                parts.append(u"{prefix}+{branch}".format(prefix=self.BRANCH_PREFIX, branch=self.branch))
        if self.version_guid:
            parts.append(u"{prefix}+{guid}".format(prefix=self.VERSION_PREFIX, guid=self.version_guid))
        return u"+".join(parts)

    def _to_deprecated_string(self):
        """Returns an 'old-style' course id, represented as 'org/course/run'"""
        return u'/'.join([self.org, self.course, self.run])

    def to_deprecated_string(self):
        """Deprecated. Use unicode(key) instead."""
        warnings.warn(
            "to_deprecated_string is deprecated! Use unicode(key) instead.",
            DeprecationWarning
        )
        return unicode(self)

    @classmethod
    def _from_deprecated_string(cls, serialized):
        """
        Return an instance of `cls` parsed from its deprecated `serialized` form.

        This will be called only if :meth:`OpaqueKey.from_string` is unable to
        parse a key out of `serialized`, and only if `set_deprecated_fallback` has
        been called to register a fallback class.

        Args:
            cls: The :class:`OpaqueKey` subclass.
            serialized (unicode): A serialized :class:`OpaqueKey`, with namespace already removed.

        Raises:
            InvalidKeyError: Should be raised if `serialized` is not a valid serialized key
                understood by `cls`.
        """
        if serialized.count('/') != 2:
            raise InvalidKeyError(cls, serialized)

        return cls(*serialized.split('/'), deprecated=True)

CourseKey.set_deprecated_fallback(CourseLocator)


class BlockUsageLocator(BlockLocatorBase, UsageKey):
    """
    Encodes a location.

    Locations address modules (aka blocks) which are definitions situated in a
    course instance. Thus, a Location must identify the course and the occurrence of
    the defined element in the course. Courses can be a version of an offering, the
    current draft head, or the current production version.

    Locators can contain both a version and a org + course + run w/ branch. The split mongo functions
    may raise errors if these conflict w/ the current db state (i.e., the course's branch !=
    the version_guid)

    Locations can express as urls as well as dictionaries. They consist of
        package_identifier: course_guid | version_guid
        block : guid
        branch : string

    BlockUsageLocators also support deprecated Location-style formatting with the following mapping:
    Location(org, course, run, category, name, revision) is represented as a BlockUsageLocator with:
      - course_key = a CourseKey comprised of (org, course, run, branch=revision)
      - block_type = category
      - block_id = name
    """
    CANONICAL_NAMESPACE = 'edx'
    KEY_FIELDS = ('course_key', 'block_type', 'block_id')

    DEPRECATED_TAG = 'i4x'  # to combine Locations with BlockUsageLocators

    # fake out class introspection as this is an attr in this class's instances
    course_key = None
    block_type = None

    DEPRECATED_URL_RE = re.compile("""
        ([^:/]+://?|/[^/]+)
        (?P<org>[^/]+)/
        (?P<course>[^/]+)/
        (?P<category>[^/]+)/     # category == block_type
        (?P<name>[^@]+)          # name == block_id
        (@(?P<revision>[^/]+))?  # branch == revision
    """, re.VERBOSE)

    # TODO (cpennington): We should decide whether we want to expand the
    # list of valid characters in a location
    DEPRECATED_INVALID_CHARS = re.compile(r"[^\w.%-]", re.UNICODE)
    # Names are allowed to have colons.
    DEPRECATED_INVALID_CHARS_NAME = re.compile(r"[^\w.:%-]", re.UNICODE)

    # html ids can contain word chars and dashes
    DEPRECATED_INVALID_HTML_CHARS = re.compile(r"[^\w-]", re.UNICODE)

    def __init__(self, course_key, block_type, block_id, **kwargs):
        """
        Construct a BlockUsageLocator
        """
        deprecated = kwargs.get('deprecated', False)
        block_id = self._parse_block_ref(block_id, deprecated)
        if block_id is None:
            raise InvalidKeyError(self.__class__, "Missing block id")

        super(BlockUsageLocator, self).__init__(course_key=course_key, block_type=block_type, block_id=block_id, **kwargs)

    @classmethod
    def _clean(cls, value, invalid):
        """
        Should only be called on deprecated-style values

        invalid should be a compiled regexp of chars to replace with '_'
        """
        return re.sub('_+', '_', invalid.sub('_', value))

    @classmethod
    def clean(cls, value):
        """
        Should only be called on deprecated-style values

        Return value, made into a form legal for locations
        """
        return cls._clean(value, cls.DEPRECATED_INVALID_CHARS)

    @classmethod
    def clean_keeping_underscores(cls, value):
        """
        Should only be called on deprecated-style values

        Return value, replacing INVALID_CHARS, but not collapsing multiple '_' chars.
        This for cleaning asset names, as the YouTube ID's may have underscores in them, and we need the
        transcript asset name to match. In the future we may want to change the behavior of _clean.
        """
        return cls.DEPRECATED_INVALID_CHARS.sub('_', value)

    @classmethod
    def clean_for_url_name(cls, value):
        """
        Should only be called on deprecated-style values

        Convert value into a format valid for location names (allows colons).
        """
        return cls._clean(value, cls.DEPRECATED_INVALID_CHARS_NAME)

    @classmethod
    def clean_for_html(cls, value):
        """
        Should only be called on deprecated-style values

        Convert a string into a form that's safe for use in html ids, classes, urls, etc.
        Replaces all INVALID_HTML_CHARS with '_', collapses multiple '_' chars
        """
        return cls._clean(value, cls.DEPRECATED_INVALID_HTML_CHARS)

    @classmethod
    def _from_string(cls, serialized):
        """
        Requests CourseLocator to deserialize its part and then adds the local deserialization of block
        """
        # Allow access to _from_string protected method
        course_key = CourseLocator._from_string(serialized)  # pylint: disable=protected-access
        parsed_parts = cls.parse_url(serialized)
        block_id = parsed_parts.get('block_id', None)
        if block_id is None:
            raise InvalidKeyError(cls, serialized)
        return cls(course_key, parsed_parts.get('block_type'), block_id)

    def version_agnostic(self):
        """
        We don't care if the locator's version is not the current head; so, avoid version conflict
        by reducing info.
        Returns a copy of itself without any version info.

        Raises:
            ValueError: if the block locator has no org, course, and run
        """
        return BlockUsageLocator(
            course_key=self.course_key.version_agnostic(),
            block_type=self.block_type,
            block_id=self.block_id,
        )

    def course_agnostic(self):
        """
        We only care about the locator's version not its course.
        Returns a copy of itself without any course info.

        Raises:
            ValueError if the block locator has no version_guid
        """
        return BlockUsageLocator(
            course_key=self.course_key.course_agnostic(),
            block_type=self.block_type,
            block_id=self.block_id
        )

    def for_branch(self, branch):
        """
        Return a UsageLocator for the same block in a different branch of the course.
        """
        return BlockUsageLocator(
            self.course_key.for_branch(branch),
            block_type=self.block_type,
            block_id=self.block_id
        )

    def for_version(self, version_guid):
        """
        Return a UsageLocator for the same block in a different branch of the course.
        """
        return BlockUsageLocator(
            self.course_key.for_version(version_guid),
            block_type=self.block_type,
            block_id=self.block_id
        )

    @classmethod
    def _parse_block_ref(cls, block_ref, deprecated=False):
        """
        Given `block_ref`, tries to parse it into a valid block reference.

        Returns `block_ref` if it is valid.

        Raises:
            InvalidKeyError: if `block_ref` is invalid.
        """
        is_local_id = isinstance(block_ref, LocalId)
        is_valid_deprecated = deprecated and cls.DEPRECATED_ALLOWED_ID_RE.match(block_ref)
        is_valid = cls.ALLOWED_ID_RE.match(block_ref)

        if (is_local_id or is_valid or is_valid_deprecated):
            return block_ref
        else:
            raise InvalidKeyError(cls, block_ref)

    @property
    def definition_key(self):  # pragma: no cover
        """
        Returns the definition key for this object.
        Undefined for Locators.
        """
        raise NotImplementedError()

    @property
    def org(self):
        """Returns the org for this object's course_key."""
        return self.course_key.org

    @property
    def course(self):
        """Returns the course for this object's course_key."""
        return self.course_key.course

    @property
    def run(self):
        """Returns the run for this object's course_key."""
        return self.course_key.run

    @property
    def package_id(self):
        """Returns the package_id for this object's course_key."""
        return self.course_key.package_id

    @property
    def branch(self):
        """Returns the branch for this object's course_key."""
        return self.course_key.branch

    @property
    def version_guid(self):
        """Returns the version guid for this object."""
        return self.course_key.version_guid

    def version(self):
        """Returns the version guid for this object."""
        return self.course_key.version_guid

    @property
    def name(self):
        """
        Deprecated. The ambiguously named field from Location which code
        expects to find. Equivalent to block_id.
        """
        warnings.warn("Name is no longer supported as a property of Locators. Please use the block_id property.", DeprecationWarning)
        return self.block_id

    def is_fully_specified(self):
        """Returns boolean; whether or not this object's course_key is fully specified."""
        return self.course_key.is_fully_specified()

    @classmethod
    def make_relative(cls, course_locator, block_type, block_id):
        """
        Return a new instance which has the given block_id in the given course
        :param course_locator: may be a BlockUsageLocator in the same snapshot
        """
        if hasattr(course_locator, 'course_key'):
            course_locator = course_locator.course_key
        return BlockUsageLocator(
            course_key=course_locator,
            block_type=block_type,
            block_id=block_id
        )

    def map_into_course(self, course_key):
        """
        Return a new instance which has the this block_id in the given course
        :param course_key: a CourseKey object representing the new course to map into
        """
        return self.replace(course_key=course_key)

    def _to_string(self):
        """
        Return a string representing this location.
        """
        # Allow access to _to_string protected method
        return u"{course_key}+{BLOCK_TYPE_PREFIX}+{block_type}+{BLOCK_PREFIX}+{block_id}".format(
            course_key=self.course_key._to_string(),  # pylint: disable=protected-access
            BLOCK_TYPE_PREFIX=self.BLOCK_TYPE_PREFIX,
            block_type=self.block_type,
            BLOCK_PREFIX=self.BLOCK_PREFIX,
            block_id=self.block_id
        )

    def html_id(self):
        """
        Generate a discussion group id based on course

        To make compatible with old Location object functionality. I don't believe this behavior fits at this
        place, but I have no way to override. We should clearly define the purpose and restrictions of this
        (e.g., I'm assuming periods are fine).
        """
        if self.deprecated:
            id_fields = [self.DEPRECATED_TAG, self.org, self.course, self.block_type, self.block_id, self.version_guid]
            id_string = u"-".join([v for v in id_fields if v is not None])
            return self.clean_for_html(id_string)
        else:
            return unicode(self)

    def _to_deprecated_string(self):
        """
        Returns an old-style location, represented as:
        i4x://org/course/category/name[@revision]  # Revision is optional
        """
        url = u"{0.DEPRECATED_TAG}://{0.course_key.org}/{0.course_key.course}/{0.block_type}/{0.block_id}".format(self)
        if self.course_key.branch:
            url += u"@{rev}".format(rev=self.course_key.branch)
        return url

    def to_deprecated_string(self):
        """Deprecated. Use unicode(key) instead."""
        warnings.warn(
            "to_deprecated_string is deprecated! Use unicode(key) instead.",
            DeprecationWarning
        )
        return unicode(self)

    @classmethod
    def _from_deprecated_string(cls, serialized):
        """
        Return an instance of `cls` parsed from its deprecated `serialized` form.

        This will be called only if :meth:`OpaqueKey.from_string` is unable to
        parse a key out of `serialized`, and only if `set_deprecated_fallback` has
        been called to register a fallback class.

        Args:
            cls: The :class:`OpaqueKey` subclass.
            serialized (unicode): A serialized :class:`OpaqueKey`, with namespace already removed.

        Raises:
            InvalidKeyError: Should be raised if `serialized` is not a valid serialized key
                understood by `cls`.
        """
        match = cls.DEPRECATED_URL_RE.match(serialized)
        if match is None:
            raise InvalidKeyError(BlockUsageLocator, serialized)
        groups = match.groupdict()
        course_key = CourseLocator(
            org=groups['org'],
            course=groups['course'],
            run=None,
            branch=groups.get('revision'),
            deprecated=True,
        )
        return cls(course_key, groups['category'], groups['name'], deprecated=True)

    def to_deprecated_son(self, prefix='', tag='i4x'):
        """
        Returns a SON object that represents this location
        """
        # This preserves the old SON keys ('tag', 'org', 'course', 'category', 'name', 'revision'),
        # because that format was used to store data historically in mongo

        # adding tag b/c deprecated form used it
        son = SON({prefix + 'tag': tag})
        for field_name in ('org', 'course'):
            # Temporary filtering of run field because deprecated form left it out
            son[prefix + field_name] = getattr(self.course_key, field_name)
        for (dep_field_name, field_name) in [('category', 'block_type'), ('name', 'block_id')]:
            son[prefix + dep_field_name] = getattr(self, field_name)

        son[prefix + 'revision'] = getattr(self.course_key, 'branch')
        return son

    @classmethod
    def _from_deprecated_son(cls, id_dict, run):
        """
        Return the Location decoding this id_dict and run
        """
        course_key = CourseLocator(
            id_dict['org'],
            id_dict['course'],
            run,
            id_dict['revision'],
            deprecated=True,
        )
        return cls(course_key, id_dict['category'], id_dict['name'], deprecated=True)

# register BlockUsageLocator as the deprecated fallback for UsageKey
UsageKey.set_deprecated_fallback(BlockUsageLocator)


class DefinitionLocator(Locator, DefinitionKey):
    """
    Container for how to locate a description (the course-independent content).
    """
    CANONICAL_NAMESPACE = 'defx'
    KEY_FIELDS = ('definition_id', 'block_type')

    # override the abstractproperty
    block_type = None
    definition_id = None

    def __init__(self, block_type, definition_id):
        if isinstance(definition_id, LocalId):
            super(DefinitionLocator, self).__init__(definition_id=definition_id, block_type=block_type)
        elif isinstance(definition_id, basestring):
            try:
                definition_id = self.as_object_id(definition_id)
            except ValueError:
                raise InvalidKeyError(self, definition_id)
            super(DefinitionLocator, self).__init__(definition_id=definition_id, block_type=block_type)
        elif isinstance(definition_id, ObjectId):
            super(DefinitionLocator, self).__init__(definition_id=definition_id, block_type=block_type)

    def _to_string(self):
        '''
        Return a string representing this location.
        unicode(self) returns something like this: "519665f6223ebd6980884f2b+type+problem"
        '''
        return u"{}+{}+{}".format(unicode(self.definition_id), self.BLOCK_TYPE_PREFIX, self.block_type)

    URL_RE = re.compile(
        r"^(?P<definition_id>[A-F0-9]+)\+{}\+(?P<block_type>{ALLOWED_ID_CHARS}+)$".format(
            Locator.BLOCK_TYPE_PREFIX, ALLOWED_ID_CHARS=Locator.ALLOWED_ID_CHARS
        ),
        re.IGNORECASE | re.VERBOSE | re.UNICODE
    )

    @classmethod
    def _from_string(cls, serialized):
        """
        Return a DefinitionLocator parsing the given serialized string
        :param serialized: matches the string to
        """
        parse = cls.URL_RE.match(serialized)
        if not parse:
            raise InvalidKeyError(cls, serialized)

        parse = parse.groupdict()
        if parse['definition_id']:
            parse['definition_id'] = cls.as_object_id(parse['definition_id'])

        return cls(**{key: parse.get(key) for key in cls.KEY_FIELDS})

    def version(self):
        """
        Returns the ObjectId referencing this specific location.
        """
        return self.definition_id


class VersionTree(object):
    """
    Holds trees of Locators to represent version histories.
    """
    def __init__(self, locator, tree_dict=None):
        """
        :param locator: must be version specific (Course has version_guid or definition had id)
        """
        if not isinstance(locator, Locator) and not inspect.isabstract(locator):
            raise TypeError("locator {} must be a concrete subclass of Locator".format(locator))
        if not locator.version():
            raise ValueError("locator must be version specific (Course has version_guid or definition had id)")
        self.locator = locator
        if tree_dict is None:
            self.children = []
        else:
            self.children = [VersionTree(child, tree_dict)
                             for child in tree_dict.get(locator.version(), [])]


class AssetLocator(BlockUsageLocator, AssetKey):
    """
    An AssetKey implementation class.
    """
    CANONICAL_NAMESPACE = 'asset-location'
    DEPRECATED_TAG = 'c4x'
    __slots__ = BlockUsageLocator.KEY_FIELDS

    ASSET_URL_RE = re.compile(r"""
        /?c4x/
        (?P<org>[^/]+)/
        (?P<course>[^/]+)/
        (?P<category>[^/]+)/
        (?P<name>[^@]+)
        (@(?P<revision>[^/]+))?
    """, re.VERBOSE | re.IGNORECASE)

    @property
    def path(self):
        return self.name

    def _to_deprecated_string(self):
        """
        Returns an old-style location, represented as:

        /c4x/org/course/category/name
        """
        url = u"/{0.DEPRECATED_TAG}/{0.course_key.org}/{0.course_key.course}/{0.block_type}/{0.block_id}".format(self)
        if self.course_key.branch:
            url += '@{}'.format(self.course_key.branch)
        return url

    @classmethod
    def _from_deprecated_string(cls, serialized):
        match = cls.ASSET_URL_RE.match(serialized)
        if match is None:
            raise InvalidKeyError(cls, serialized)
        groups = match.groupdict()
        course_key = CourseLocator(
            groups['org'],
            groups['course'],
            None,
            groups.get('revision', None),
            deprecated=True
        )

        return cls(course_key, groups['category'], groups['name'], deprecated=True)

    def to_deprecated_list_repr(self):
        """
        Thumbnail locations are stored as lists [c4x, org, course, thumbnail, path, None] in contentstore.mongo
        That should be the only use of this method, but the method is general enough to provide the pre-opaque
        Location fields as an array in the old order with the tag.
        """
        return ['c4x', self.org, self.course, self.block_type, self.name, None]

# Register AssetLocator as the deprecated fallback for AssetKey
AssetKey.set_deprecated_fallback(AssetLocator)