#!/usr/bin/env python3

import logging
import datetime
import re
import enum
import os
from pycaching import errors
from pycaching.geo import Point
from pycaching.trackable import Trackable
from pycaching.log import Log, Type as LogType
from pycaching.util import parse_date, rot13, lazy_loaded

# prefix _type() function to avoid colisions with cache type
_type = type


class Cache(object):
    """Represents a geocache with its properties and methods for loading them.

    Provides some getters and setters for geocache properties like name, size, terrain, etc.
    Also contains two possibile methods to load cache details and ensures, that these methods
    are called when accessing a property which hasn't been filled yet.

    There are also methods for posting and loadings logs here. For more detail about Logs, please
    refer to :class:`.Log`.

    In summary, this class contains everything, which is possible to see or do on geocache page
    on geocaching.com.
    """

    # generated by Util.get_possible_attributes()
    # TODO: smarter way of keeping attributes up to date
    _possible_attributes = {
        "abandonedbuilding": "Abandoned Structure",
        "available": "Available at All Times",
        "bicycles": "Bicycles",
        "boat": "Boat",
        "campfires": "Campfires",
        "camping": "Camping Available",
        "cliff": "Cliff / Falling Rocks",
        "climbing": "Difficult Climbing",
        "cow": "Watch for Livestock",
        "danger": "Dangerous Area",
        "dangerousanimals": "Dangerous Animals",
        "dogs": "Dogs",
        "fee": "Access or Parking Fee",
        "field_puzzle": "Field Puzzle",
        "firstaid": "Needs Maintenance",
        "flashlight": "Flashlight Required",
        "food": "Food Nearby",
        "frontyard": "Front Yard(Private Residence)",
        "fuel": "Fuel Nearby",
        "geotour": "GeoTour Cache",
        "hike_long": "Long Hike (+10km)",
        "hike_med": "Medium Hike (1km-10km)",
        "hike_short": "Short Hike (Less than 1km)",
        "hiking": "Significant Hike",
        "horses": "Horses",
        "hunting": "Hunting",
        "jeeps": "Off-Road Vehicles",
        "kids": "Recommended for Kids",
        "landf": "Lost And Found Tour",
        "mine": "Abandoned Mines",
        "motorcycles": "Motortcycles",
        "night": "Recommended at Night",
        "nightcache": "Night Cache",
        "onehour": "Takes Less Than an Hour",
        "parking": "Parking Available",
        "parkngrab": "Park and Grab",
        "partnership": "Partnership Cache",
        "phone": "Telephone Nearby",
        "picnic": "Picnic Tables Nearby",
        "poisonoak": "Poisonous Plants",
        "public": "Public Transportation",
        "quads": "Quads",
        "rappelling": "Climbing Gear",
        "restrooms": "Public Restrooms Nearby",
        "rv": "Truck Driver/RV",
        "s-tool": "Special Tool Required",
        "scenic": "Scenic View",
        "scuba": "Scuba Gear",
        "seasonal": "Seasonal Access",
        "skiis": "Cross Country Skis",
        "snowmobiles": "Snowmobiles",
        "snowshoes": "Snowshoes",
        "stealth": "Stealth Required",
        "stroller": "Stroller Accessible",
        "swimming": "May Require Swimming",
        "teamwork": "Teamwork Required",
        "thorn": "Thorns",
        "ticks": "Ticks",
        "touristok": "Tourist Friendly",
        "treeclimbing": "Tree Climbing",
        "uv": "UV Light Required",
        "wading": "May Require Wading",
        "water": "Drinking Water Nearby",
        "wheelchair": "Wheelchair Accessible",
        "winter": "Available During Winter",
        "wirelessbeacon": "Wireless Beacon"
    }

    # collection of urls used within the Cache class
    _urls = {
        "tiles_server": "http://tiles01.geocaching.com/map.details",
        "logbook": "seek/geocache.logbook",
        "cache_details": "seek/cache_details.aspx",
        "print_page": "seek/cdpf.aspx",
        "log_page": "play/geocache/{wp}/log",
    }

    def __init__(self, geocaching, wp, **kwargs):
        """Create a cache instance.

        :param .Geocaching geocaching: Reference to :class:`.Geocaching` instance, used for loading
            cache data.
        :param str wp: Cache GC Code, eg. "GC1PAR2".
        :param **kwargs: Other cache properties. For possible keywords, please see class properites.
        """

        self.geocaching = geocaching
        if wp is not None:
            self.wp = wp

        known_kwargs = {"name", "type", "location", "original_location", "state", "found", "size",
                        "difficulty", "terrain", "author", "hidden", "attributes", "summary",
                        "description", "hint", "favorites", "pm_only", "url", "waypoints", "_logbook_token",
                        "_trackable_page_url", "guid"}

        for name in known_kwargs:
            if name in kwargs:
                setattr(self, name, kwargs[name])

    def __str__(self):
        """Return cache GC code."""
        return self._wp  # not to trigger lazy_loading !

    def __eq__(self, other):
        """Compare caches by their GC code and contained :class:`.Geocaching` reference."""
        return self.geocaching == other.geocaching and self.wp == other.wp

    @classmethod
    def from_trackable(cls, trackable):
        """Return :class:`.Cache` instance from :class:`.Trackable`.

        This only makes sense, if trackable is currently placed in cache. Otherwise it will have
        unexpected behavior.

        :param .Trackable trackable: Source trackable.
        """
        # TODO handle trackables which are not in cache
        return cls(trackable.geocaching, None, url=trackable.location_url)

    @classmethod
    def from_block(cls, block):
        """Return :class:`.Cache` instance from :class:`.Block`.

        Used during quick search. The Cache will have only GC code, name and approximate location
        filled in.

        :param .Block block: Source block
        """
        c = cls(block.tile.geocaching, block.cache_wp, name=block.cache_name)
        c.location = Point.from_block(block)
        return c

    @property
    def wp(self):
        """The cache GC code, must start with :code:`GC`.

        :type: :class:`str`
        """
        return self._wp

    @wp.setter
    def wp(self, wp):
        wp = str(wp).upper().strip()
        if not wp.startswith("GC"):
            raise errors.ValueError("GC code '{}' doesn't start with 'GC'.".format(wp))
        self._wp = wp

    @property
    def guid(self):
        """The cache GUID. An identifier used at some places on geoaching.com

        :type: :class:`str`
        """
        return getattr(self, "_guid", None)

    @guid.setter
    def guid(self, guid):
        guid = guid.strip()
        guid_regex = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        if not re.match(guid_regex, guid):
            raise errors.ValueError("GUID not well formatted: {}".format(guid))
        self._guid = guid

    @property
    def geocaching(self):
        """A reference to :class:`.Geocaching` used for communicating with geocaching.com.

        :type: :class:`.Geocaching` instance
        """
        return self._geocaching

    @geocaching.setter
    def geocaching(self, geocaching):
        if not hasattr(geocaching, "_request"):
            raise errors.ValueError("Passed object (type: '{}')"
                                    "doesn't contain '_request' method.".format(_type(geocaching)))
        self._geocaching = geocaching

    @property
    @lazy_loaded
    def name(self):
        """A human readable name of cache.

        :type: :class:`str`
        """
        return self._name

    @name.setter
    def name(self, name):
        name = str(name).strip()
        self._name = name

    @property
    @lazy_loaded
    def location(self):
        """The cache location.

        :setter: Set a cache location. If :class:`str` is passed, then :meth:`.Point.from_string`
            is used and its return value is stored as a location.
        :type: :class:`.Point`
        """
        return self._location

    @location.setter
    def location(self, location):
        if _type(location) is str:
            location = Point.from_string(location)
        elif _type(location) is not Point:
            raise errors.ValueError(
                "Passed object is not Point instance nor string containing coordinates.")
        self._location = location

    @property
    @lazy_loaded
    def original_location(self):
        """The cache original location.

        :setter: Set a cache original location. If :class:`str` is passed, then
        :meth:`.Point.from_string` is used and its return value is stored as a location.
        :type: :class:`.Point`
        """
        return self._original_location

    @original_location.setter
    def original_location(self, original_location):
        if _type(original_location) is str:
            original_location = Point.from_string(original_location)
        elif _type(original_location) is not Point and original_location is not None:
            raise errors.ValueError(
                "Passed object is not Point instance nor string containing coordinates.")
        self._original_location = original_location

    @property
    @lazy_loaded
    def waypoints(self):
        """Any waypoints listed in the cache.

        :setter: Store a dictionary of locations using their lookup.
        :type: :class:`dict`
        """
        return self._waypoints

    @waypoints.setter
    def waypoints(self, waypoints):
        self._waypoints = waypoints

    @property
    @lazy_loaded
    def type(self):
        """The cache type.

        :setter: Set a cache type. If :class:`str` is passed, then :meth:`.cache.Type.from_string`
            is used and its return value is stored as a type.
        :type: :class:`.cache.Type`
        """
        return self._type

    @type.setter
    def type(self, type):
        if _type(type) is not Type:
            type = Type.from_string(type)
        self._type = type

    @property
    @lazy_loaded
    def state(self):
        """The cache status.

        :code:`True` if cache is enabled, :code:`False` if cache is disabled.

        :type: :class:`bool`
        """
        return self._state

    @state.setter
    def state(self, state):
        self._state = bool(state)

    @property
    @lazy_loaded
    def found(self):
        """The cache found status.

        :code:`True` if cache is found by current user, :code:`False` if not.

        :type: :class:`bool`
        """
        return self._found

    @found.setter
    def found(self, found):
        self._found = bool(found)

    @property
    @lazy_loaded
    def size(self):
        """The cache size.

        :setter: Set a cache size. If :class:`str` is passed, then :meth:`.cache.Size.from_string`
            is used and its return value is stored as a size.
        :type: :class:`.cache.Size`
        """
        return self._size

    @size.setter
    def size(self, size):
        if _type(size) is not Size:
            size = Size.from_string(size)
        self._size = size

    @property
    @lazy_loaded
    def difficulty(self):
        """The cache difficulty.

        :setter: Set a cache difficulty. It must be in a common range - 1 to 5 in 0.5 steps.
        :type: :class:`float`
        """
        return self._difficulty

    @difficulty.setter
    def difficulty(self, difficulty):
        difficulty = float(difficulty)
        if difficulty < 1 or difficulty > 5 or difficulty * 10 % 5 != 0:  # X.0 or X.5
            raise errors.ValueError("Difficulty must be from 1 to 5 and divisible by 0.5.")
        self._difficulty = difficulty

    @property
    @lazy_loaded
    def terrain(self):
        """The cache terrain.

        :setter: Set a cache terrain. It must be in a common range - 1 to 5 in 0.5 steps.
        :type: :class:`float`
        """
        return self._terrain

    @terrain.setter
    def terrain(self, terrain):
        terrain = float(terrain)
        if terrain < 1 or terrain > 5 or terrain * 10 % 5 != 0:  # X.0 or X.5
            raise errors.ValueError("Terrain must be from 1 to 5 and divisible by 0.5.")
        self._terrain = terrain

    @property
    @lazy_loaded
    def author(self):
        """The cache author.

        :type: :class:`str`
        """
        return self._author

    @author.setter
    def author(self, author):
        author = str(author).strip()
        self._author = author

    @property
    @lazy_loaded
    def hidden(self):
        """The cache hidden date.

        :setter: Set a cache hidden date. If :class:`str` is passed, then :meth:`.util.parse_date`
            is used and its return value is stored as a date.
        :type: :class:`datetime.date`
        """
        return self._hidden

    @hidden.setter
    def hidden(self, hidden):
        if _type(hidden) is str:
            hidden = parse_date(hidden)
        elif _type(hidden) is not datetime.date:
            raise errors.ValueError(
                "Passed object is not datetime.date instance nor string containing a date.")
        self._hidden = hidden

    @property
    @lazy_loaded
    def attributes(self):
        """The cache attributes.

        :setter: Set a cache attributes. Walk through passed :class:`dict` and use :class:`str`
            keys as attribute names and :class:`bool` values as positive / negative attributes.
            Unknown attributes are ignored with warning (you can find possible attribute keys
            in :attr:`.Cache._possible_attributes`).
        :type: :class:`dict`
        """
        return self._attributes

    @attributes.setter
    def attributes(self, attributes):
        if _type(attributes) is not dict:
            raise errors.ValueError("Attribues is not dict.")

        self._attributes = {}
        for name, allowed in attributes.items():
            name = name.strip().lower()
            if name in self._possible_attributes:
                self._attributes[name] = allowed
            else:
                logging.warning("Unknown attribute {}, ignoring.".format(name))

    @property
    @lazy_loaded
    def summary(self):
        """The cache text summary.

        :type: :class:`str`
        """
        return self._summary

    @summary.setter
    def summary(self, summary):
        summary = str(summary).strip()
        self._summary = summary

    @property
    @lazy_loaded
    def description(self):
        """The cache long description.

        :type: :class:`str`
        """
        return self._description

    @description.setter
    def description(self, description):
        description = str(description).strip()
        self._description = description

    @property
    @lazy_loaded
    def hint(self):
        """The cache hint.

        :setter: Set a cache hint. Don't decode text, you have to use :meth:`.util.rot13` before.
        :type: :class:`str`
        """
        return self._hint

    @hint.setter
    def hint(self, hint):
        hint = str(hint).strip()
        self._hint = hint

    @property
    @lazy_loaded
    def favorites(self):
        """The cache favorite points.

        :type: :class:`int`
        """
        return self._favorites

    @favorites.setter
    def favorites(self, favorites):
        self._favorites = int(favorites)

    @property
    def pm_only(self):
        """If the cache is PM only.

        :type: :class:`bool`
        """
        return self._pm_only

    @pm_only.setter
    def pm_only(self, pm_only):
        self._pm_only = bool(pm_only)

    @property
    @lazy_loaded
    def _logbook_token(self):
        """The token used to load logbook pages for cache.

        :type: :class:`str`
        """
        return self.__logbook_token

    @_logbook_token.setter
    def _logbook_token(self, logbook_token):
        self.__logbook_token = logbook_token

    @property
    @lazy_loaded
    def _trackable_page_url(self):
        """The URL of page containing all trackables stored in this cache.

        :type: :class:`str`
        """
        return self.__trackable_page_url

    @_trackable_page_url.setter
    def _trackable_page_url(self, trackable_page_url):
        self.__trackable_page_url = trackable_page_url

    def load(self):
        """Load all possible cache details.

        Use full cache details page. Therefore all possible properties are filled in, but the
        loading is a bit slow.

        If you want to load basic details about a PM only cache, the :class:`.PMOnlyException` is
        still thrown, but avaliable details are filled in. If you know, that the cache you are
        loading is PM only, please consider using :meth:`load_quick` as it will load the same
        details, but quicker.

        .. note::
           This method is called automatically when you access a property which isn't yet filled in
           (so-called "lazy loading"). You don't have to call it explicitly.

        :raise .PMOnlyException: If cache is PM only and current user is basic member.
        :raise .LoadError: If cache loading fails (probably because of not existing cache).
        """
        try:
            # pick url based on what info we have right now
            if hasattr(self, "url"):
                root = self.geocaching._request(self.url)
            elif hasattr(self, "_wp"):
                root = self.geocaching._request(self._urls["cache_details"],
                                                params={"wp": self._wp})
            else:
                raise errors.LoadError("Cache lacks info for loading")
        except errors.Error as e:
            # probably 404 during cache loading - cache not exists
            raise errors.LoadError("Error in loading cache") from e

        # check for PM only caches if using free account
        self.pm_only = root.find("section", "pmo-banner") is not None

        cache_details = root.find(id="ctl00_divContentMain") if self.pm_only else root.find(id="cacheDetails")

        # details also avaliable for basic members for PM only caches -----------------------------

        if self.pm_only:
            self.wp = cache_details.find("li", "li__gccode").text.strip()

            self.name = cache_details.find("h1").text.strip()

            author = cache_details.find(id="ctl00_ContentBody_uxCacheBy").text
            self.author = author[len("A cache by "):]

            # parse cache detail list into a python list
            details = cache_details.find("ul", "ul__hide-details").text.split("\n")

            self.difficulty = float(details[2])

            self.terrain = float(details[5])

            self.size = Size.from_string(details[8])

            self.favorites = int(details[11])
        else:
            # parse from <title> - get first word
            try:
                self.wp = root.title.string.split(" ")[0]
            except:
                raise errors.LoadError
            self.name = cache_details.find("h2").text

            self.author = cache_details("a")[1].text

            size = root.find("div", "CacheSize")

            D_and_T_img = root.find("div", "CacheStarLabels").find_all("img")

            size = size.find("img").get("src")  # size img src
            size = size.split("/")[-1].rsplit(".", 1)[0]  # filename w/o extension
            self.size = Size.from_filename(size)

            self.difficulty, self.terrain = [float(img.get("alt").split()[0]) for img in D_and_T_img]

        type = cache_details.find("img").get("src")  # type img src
        type = type.split("/")[-1].rsplit(".", 1)[0]  # filename w/o extension
        self.type = Type.from_filename(type)

        if self.pm_only:
            raise errors.PMOnlyException()

        # details not avaliable for basic members for PM only caches ------------------------------
        pm_only_warning = root.find("p", "Warning NoBottomSpacing")
        self.pm_only = pm_only_warning and ("Premium Member Only" in pm_only_warning.text) or False

        attributes_widget, inventory_widget, *_ = root.find_all("div", "CacheDetailNavigationWidget")

        hidden = cache_details.find("div", "minorCacheDetails").find_all("div")[1].text
        self.hidden = parse_date(hidden.split(":")[-1])

        self.location = Point.from_string(root.find(id="uxLatLon").text)

        self.state = root.find("ul", "OldWarning") is None

        found = root.find("div", "FoundStatus")
        self.found = found and ("Found It!" or "Attended" in found.text) or False

        attributes_raw = attributes_widget.find_all("img")
        attributes_raw = [_.get("src").split("/")[-1].rsplit("-", 1) for _ in attributes_raw]

        self.attributes = {attribute_name: appendix.startswith("yes") for attribute_name, appendix
                           in attributes_raw if not appendix.startswith("blank")}

        user_content = root.find_all("div", "UserSuppliedContent")
        self.summary = user_content[0].text
        self.description = str(user_content[1])

        self.hint = rot13(root.find(id="div_hint").text.strip())

        favorites = root.find("span", "favorite-value")
        self.favorites = 0 if favorites is None else int(favorites.text)

        js_content = "\n".join(map(lambda i: i.text, root.find_all("script")))
        self._logbook_token = re.findall("userToken\\s*=\\s*'([^']+)'", js_content)[0]
        # find original location if any
        if "oldLatLng\":" in js_content:
            old_lat_long = js_content.split("oldLatLng\":")[1].split(']')[0].split('[')[1]
            self.original_location = Point(old_lat_long)
        else:
            self.original_location = None

        # if there are some trackables
        if len(inventory_widget.find_all("a")) >= 3:
            trackable_page_url = inventory_widget.find(id="ctl00_ContentBody_uxTravelBugList_uxViewAllTrackableItems")
            self._trackable_page_url = trackable_page_url.get("href")[3:]  # has "../" on start
        else:
            self._trackable_page_url = None

        # Additional Waypoints
        self.waypoints = Waypoint.from_html(root, "ctl00_ContentBody_Waypoints")

        logging.debug("Cache loaded: {}".format(self))

    def load_quick(self):
        """Load basic cache details.

        Use information from geocaching map tooltips. Therefore loading is very quick, but
        the only loaded properties are: `name`, `type`, `state`, `size`, `difficulty`, `terrain`,
        `hidden`, `author`, `favorites` and `pm_only`.

        :raise .LoadError: If cache loading fails (probably because of not existing cache).
        """
        res = self.geocaching._request(self._urls["tiles_server"],
                                       params={"i": self.wp},
                                       expect="json")

        if res["status"] == "failed" or len(res["data"]) != 1:
            msg = res["msg"] if "msg" in res else "Unknown error (probably not existing cache)"
            raise errors.LoadError("Cache {} cannot be loaded: {}".format(self, msg))

        data = res["data"][0]

        # prettify data
        self.name = data["name"]
        self.type = Type.from_string(data["type"]["text"])
        self.state = data["available"]
        self.size = Size.from_string(data["container"]["text"])
        self.difficulty = data["difficulty"]["text"]
        self.terrain = data["terrain"]["text"]
        self.hidden = parse_date(data["hidden"])
        self.author = data["owner"]["text"]
        self.favorites = int(data["fp"])
        self.pm_only = data["subrOnly"]
        self.guid = res["data"][0]["g"]

        logging.debug("Cache loaded: {}".format(self))

    def load_by_guid(self):
        """Load cache details using the GUID to request and parse the caches
        'print-page'. Loading as many properties as possible except the
        following ones, since they are not present on the 'print-page':

          + original_location
          + state
          + found
          + pm_only

        :raise .PMOnlyException: If the PM only warning is shown on the page
        """
        # If GUID has not yet been set, load it using the "tiles_server"
        # utilizing `load_quick()`
        if not self.guid:
            self.load_quick()

        res = self.geocaching._request(self._urls["print_page"],
                                       params={"guid": self.guid})
        if res.find("p", "Warning") is not None:
            raise errors.PMOnlyException()
        content = res.find(id="Content")

        self.name = content.find("h2").text

        self.location = Point.from_string(
            content.find("p", "LatLong Meta").text)

        type_img = os.path.basename(content.find("img").get("src"))
        self.type = Type.from_filename(os.path.splitext(type_img)[0])

        size_img = content.find("img", src=re.compile("\/icons\/container\/"))
        self.size = Size.from_string(size_img.get("alt").split(": ")[1])

        D_and_T_img = content.find("p", "Meta DiffTerr").find_all("img")
        self.difficulty, self.terrain = [
            float(img.get("alt").split()[0]) for img in D_and_T_img
        ]

        self.author = content.find(
            "p", text=re.compile("Placed by:")).text.split("\r\n")[2].strip()

        hidden_p = content.find("p", text=re.compile("Placed Date:"))
        self.hidden = hidden_p.text.replace("Placed Date:", "").strip()

        attr_img = content.find_all("img", src=re.compile("\/attributes\/"))
        attributes_raw = [
            os.path.basename(_.get("src")).rsplit("-", 1) for _ in attr_img
        ]
        self.attributes = {
            name: appendix.startswith("yes") for name, appendix
            in attributes_raw if not appendix.startswith("blank")
        }

        self.summary = content.find(
            "h2", text="Short Description").find_next("div").text

        self.description = content.find(
            "h2", text="Long Description").find_next("div").text

        self.hint = content.find(id="uxEncryptedHint").text

        self.favorites = content.find(
            "strong", text=re.compile("Favorites:")).parent.text.split()[-1]

        self.waypoints = Waypoint.from_html(content, "Waypoints")

    def _logbook_get_page(self, page=0, per_page=25):
        """Load one page from logbook.

        :param int page: Logbook page to load.
        :param int per_page: Logs per page (used to calculate start index).
        :raise .LoadError: If loading fails.
        """
        res = self.geocaching._request(self._urls["logbook"], params={
            "tkn": self._logbook_token,  # will trigger lazy_loading if needed
            "idx": int(page) + 1,  # Groundspeak indexes this from 1 (OMG..)
            "num": int(per_page),
            "decrypt": "true"
        }, expect="json")

        if res["status"] != "success":
            error_msg = res["msg"] if "msg" in res else "Unknown error"
            raise errors.LoadError("Logbook cannot be loaded: {}".format(error_msg))

        return res["data"]

    def load_logbook(self, limit=float("inf")):
        """Return a generator of logs for this cache.

        Yield instances of :class:`.Log` filled with log data.

        :param int limit: Maximum number of logs to generate.
        """
        logging.info("Loading logbook for {}...".format(self))

        page = 0
        per_page = min(limit, 100)  # max number to fetch in one request is 100 items

        while True:
            # get one page
            logbook_page = self._logbook_get_page(page, per_page)
            page += 1

            if not logbook_page:
                # result is empty - no more logs
                raise StopIteration()

            for log_data in logbook_page:

                limit -= 1  # handle limit
                if limit < 0:
                    raise StopIteration()

                img_filename = log_data["LogTypeImage"].rsplit(".", 1)[0]  # filename w/o extension

                # create and fill log object
                l = Log()
                l.type = LogType.from_filename(img_filename)
                l.text = log_data["LogText"]
                l.visited = log_data["Visited"]
                l.author = log_data["UserName"]
                yield l

    # TODO: trackable list can have multiple pages - handle it in similar way as _logbook_get_page
    # for example see: http://www.geocaching.com/geocache/GC26737_geocaching-jinak-tb-gc-hrbitov
    def load_trackables(self, limit=float("inf")):
        """Return a generator of trackables in this cache.

        Yield instances of :class:`.Trackable` filled with trackable data.

        :param int limit: Maximum number of trackables to generate.
        """
        logging.info("Loading trackables for {}...".format(self))
        self.trackables = []

        url = self._trackable_page_url  # will trigger lazy_loading if needed
        if not url:
            # no link to all trackables = no trackables in cache
            raise StopIteration()
        res = self.geocaching._request(url)

        trackable_table = res.find_all("table")[1]
        links = trackable_table.find_all("a")
        # filter out all urls for trackables
        urls = [link.get("href") for link in links if "track" in link.get("href")]
        # find the names matching the trackble urls
        names = [re.split("[\<\>]", str(link))[2] for link in links if "track" in link.get("href")]

        for name, url in zip(names, urls):

            limit -= 1  # handle limit
            if limit < 0:
                raise StopIteration()

            # create and fill trackable object
            t = Trackable(self.geocaching, None)
            t.name = name
            t.url = url
            self.trackables.append(t)
            yield t

    def _get_log_page_url(self):
        return self._urls["log_page"].format(wp=self.wp.lower())

    def _load_log_page(self):
        """Load a logging page for this cache.

        :return: Tuple of data nescessary to log the cache.
        :rtype: :class:`tuple` of (:class:`set`:, :class:`dict`, class:`str`)
        """
        log_page = self.geocaching._request(self._get_log_page_url())

        # find all valid log types for the cache
        valid_types = {o["value"] for o in log_page.find("select", attrs={"name": "LogTypeId"}).find_all("option")}

        # find all static data fields needed for log
        hidden_inputs = log_page.find_all("input", type=["hidden", "submit"])
        hidden_inputs = {i["name"]: i.get("value", "") for i in hidden_inputs}

        return valid_types, hidden_inputs

    def post_log(self, log):
        """Post a log for this cache.

        :param .Log log: Previously created :class:`Log` filled with data.
        """
        if not log.text:
            raise errors.ValueError("Log text is empty")

        valid_types, hidden_inputs = self._load_log_page()
        if log.type.value not in valid_types:
            raise errors.ValueError("The cache does not accept this type of log")

        # assemble post data
        post = hidden_inputs
        post["LogTypeId"] = log.type.value
        post["LogDate"] = log.visited.strftime("%Y-%m-%d")
        post["LogText"] = log.text

        self.geocaching._request(self._get_log_page_url(), method="POST", data=post)


class Waypoint():
    """Waypoint represents a waypoint related to the cache. This may be a
       Parking spot, a stage in a multi-cache or similar.

       :param str identifier: the unique identifier of the location
       :param str type: type of waypoint
       :param Point location: waypoint coordinates
       :param str note: Information about the waypoint
    """
    def __init__(self, id=None, type=None, location=None, note=None):
        self._identifier = id
        self._type = type
        self._location = location
        self._note = note

    @classmethod
    def from_html(cls, soup, table_id):
        """Return a dictionary of all waypoints found in the page
        representation

        :param bs4.BeautifulSoup soup: parsed html document containing the
            waypoints table
        :param str table_id: html id of the waypoints table
        """
        waypoints_dict = {}
        waypoints_table = soup.find('table', id=table_id)
        if waypoints_table:
            waypoints_table = waypoints_table.find_all("tr")
            for r1, r2 in zip(waypoints_table[1::2], waypoints_table[2::2]):
                columns = r1.find_all("td") + r2.find_all("td")
                identifier = columns[4].text.strip()
                type = columns[2].find("img").get("title")
                location_string = columns[6].text.strip()
                try:
                    loc = Point(location_string)
                except ValueError:
                    loc = None
                    logging.debug("No valid location format in waypoint {}: {}".format(
                        identifier, location_string))
                note = columns[10].text.strip()
                waypoints_dict[identifier] = cls(identifier, type, loc, note)
        return waypoints_dict

    def __str__(self):
        return self.identifier

    @property
    def identifier(self):
        """The waypoint unique identifier.

        :type: :class:`str`
        """
        return self._identifier

    @identifier.setter
    def identifier(self, identifier):
        self._identifier = identifier

    @property
    def type(self):
        """The waypoint type.

        :type: :class:`str`
        """
        return self._type

    @type.setter
    def type(self, type):
        self._type = type

    @property
    def location(self):
        """The waypoint location.

        :type: :class:`.Point`
        """
        return self._location

    @location.setter
    def location(self, location):
        if _type(location) is str:
            location = Point.from_string(location)
        elif _type(location) is not Point:
            raise errors.ValueError(
                "Passed object is not Point instance nor string containing coordinates.")
        self._location = location

    @property
    def note(self):
        """Any additional information about the waypoint.

        :type: :class:`str`
        """
        return self._note

    @note.setter
    def note(self, note):
        self._note = note


class Type(enum.Enum):
    """Enum of possible cache types.

    Values are cache image filenames - http://www.geocaching.com/images/WptTypes/[VALUE].gif
    """

    traditional = "2"
    multicache = "3"
    mystery = unknown = "8"
    letterbox = "5"
    event = "6"
    mega_event = "mega"
    giga_event = "giga"
    earthcache = "137"
    cito = cache_in_trash_out_event = "13"
    webcam = "11"
    virtual = "4"
    wherigo = "1858"
    lost_and_found_event = "10Years_32"
    project_ape = "ape_32"
    groundspeak_hq = "HQ_32"
    gps_adventures_exhibit = "1304"
    groundspeak_block_party = "4738"
    locationless = reverse = "12"

    @classmethod
    def from_filename(cls, filename):
        """Return a cache type from its image filename."""
        if filename == "earthcache":
            # fuck Groundspeak, they use 2 exactly same icons with 2 different names
            filename = "137"
        return cls(filename)

    @classmethod
    def from_string(cls, name):
        """Return a cache type from its human readable name.

        :raise .ValueError: If cache type cannot be determined.
        """
        name = name.replace(" Geocache", "")  # with space!
        name = name.replace(" Cache", "")  # with space!
        name = name.lower().strip()

        name_mapping = {
            "traditional": cls.traditional,
            "multi-cache": cls.multicache,
            "mystery": cls.mystery,
            "unknown": cls.unknown,
            "letterbox hybrid": cls.letterbox,
            "event": cls.event,
            "mega-event": cls.mega_event,
            "giga-event": cls.giga_event,
            "earthcache": cls.earthcache,
            "cito": cls.cito,
            "cache in trash out event": cls.cache_in_trash_out_event,
            "webcam": cls.webcam,
            "virtual": cls.virtual,
            "wherigo": cls.wherigo,
            "lost and found event": cls.lost_and_found_event,
            "project ape": cls.project_ape,
            "groundspeak hq": cls.groundspeak_hq,
            "gps adventures exhibit": cls.gps_adventures_exhibit,
            "groundspeak block party": cls.groundspeak_block_party,
            "locationless (reverse)": cls.locationless,
        }

        try:
            return name_mapping[name]
        except KeyError as e:
            raise errors.ValueError("Unknown cache type '{}'.".format(name)) from e


class Size(enum.Enum):
    """Enum of possible cache sizes.

    Naming follows Groundspeak image filenames, values are human readable names.
    """

    micro = "micro"
    small = "small"
    regular = "regular"
    large = "large"
    not_chosen = "not chosen"
    virtual = "virtual"
    other = "other"

    @classmethod
    def from_filename(cls, filename):
        """Return a cache size from its image filename."""
        return cls[filename]

    @classmethod
    def from_string(cls, name):
        """Return a cache size from its human readable name.

        :raise .ValueError: If cache size cannot be determined.
        """
        name = name.strip().lower()

        try:
            return cls(name)
        except ValueError as e:
            raise errors.ValueError("Unknown cache size '{}'.".format(name)) from e
