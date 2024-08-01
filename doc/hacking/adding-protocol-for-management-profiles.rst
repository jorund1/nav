===============================================================
Adding support for a new protocol in management profiles
===============================================================

This guide shows how to add a new protocol option for management
profiles.

A quick intro to management profiles
====================================

A netbox can have any number of management profiles. A management
profile represents a specific protocol that we can use to communicate
with the netbox and the configuration details needed to do so. The
configuration details are supplied by the user in the *Management
Profile* tab when seeding the database using the web interface.

Every management profile has a default set of details:
*name*, *description*, and *protocol ID*. For some simple protocols,
this may be enough. A management profile can also have custom
configuration data. For example, a management profile representing the
HTTP Rest API protocol would probably need to include the *TCP port*
of the Rest server as a configuration detail.

The goal
========

Add the option to specify "HTTP Rest API" as the protocol for a
management profile.


Code
====

Protocol without custom configuration details
---------------------------------------------

Adding a protocol that only uses the default set of profile
data (*name*, *description*, and *protocol ID*) and no custom
configuration details is simple. In the :py:class:`ManagementProfile`
class, declare a suitingly named PROTOCOL constant and add it to
``ManagementProfile.PROTOCOL_CHOICES``:

.. code-block:: python
    :caption: python/nav/models/manage.py

    class ManagementProfile(models.Model):
        PROTOCOL_SNMP = 1
        PROTOCOL_NAPALM = 2
        PROTOCOL_SNMPV3 = 3
        PROTOCOL_HTTP_REST = 4  # Our new PROTOCOL constant, holds the new protocol's ID
        PROTOCOL_CHOICES = [
            (PROTOCOL_SNMP, "SNMP"),
            (PROTOCOL_NAPALM, "NAPALM"),
            (PROTOCOL_SNMPV3, "SNMPv3"),
            (PROTOCOL_HTTP_REST, "HTTP Rest API"),  # Used when listing protocols in the web form
        ]


.. image:: add-management-profile-basic.png

After this change, users will be able to add new management profiles
with the new protocol in the web interface (bulk import is also
supported). Users can then assign the management profile to netboxes
to inform NAV that they support that protocol.

.. tip:: In ipdevpoll plugins where you pull data from a netbox
         using the new protocol, you can with this basic management
         profile now determine if the plugin supports a given netbox by
         checking if the netbox's list of management profiles has a
         management profile with protocol id matching your new protocol.


Adding custom configuration details
-----------------------------------
After adding a new protocol ID constant in
:py:class:`ManagementProfile` and appending it to ``PROTOCOL_CHOICES``
(see above), the web form for adding a new management profile allows
for assigning management profiles the new protocol id.

We now want to extend the web form so that it allows assigning custom
configuration details that will be stored in the profile's
``ManagementProfile.configuration`` dict after the form is
processed. To do this (see also the code block below),

* create a Django ModelForm form (by subclassing :py:class:`django.forms.ModelForm`) in ``python/nav/web/seeddb/page/management_profile/forms.py``. It should have one field per entry you want stored in the profile's ``ManagementProfile.configuration`` dict after the form is processed,

* make this form also inherit the :py:class:`ProtocolSpecificMixin` mixin (which needs to come before :py:class:`django.forms.ModelForm` in the method resolution order), and

* declare the ``PROTOCOL`` and ``PROTOCOL_CHOICES`` constants so that NAV is able to discern which protocol's config this form represents.

.. note::
    exchange ``PROTOCOL_HTTP_REST`` below with the name of your new
    protocol's constant.

.. code-block:: python
    :caption: python/nav/web/seeddb/page/management_profile/forms.py

    class HttpRestForm(ProtocolSpecificMixIn, forms.ModelForm):
        PROTOCOL = ManagementProfile.PROTOCOL_HTTP_REST
        PROTOCOL_CHOICES = PROTOCOL_CHOICES.get(PROTOCOL)

        class Meta(object):
            model = ManagementProfile
            configuration_fields = ['https', 'tcp_port'] # These are the keys of the custom configuration
            fields = []

        # This becomes the value of ManagementProfile.configuration["https"]
        https = forms.BooleanField(
            initial=True,
            required=False,
            label="Use https",
            help_text="Uncheck this if http should be used instead of https",
        )

        # This becomes the value of ManagementProfile.configuration["tcp_port"]
        tcp_port = forms.IntegerField(
            required=True,
            help_text="TCP port that the HTTP Rest server listens to",
            min_value=1,
            max_value=65535,
        )

.. image:: add-management-profile-custom.png

This form will now be remembered as the custom configuration form for
your new protocol, (namely because the form inherits
:py:class:`ProtocolSpecificMixIn` and declares the new protocol's ID
in ``ProtocolSpecificMixIn.PROTOCOL``. Nav searches all subclasses of
:py:class:`ProtocolSpecificMixIn` on module load). The form will be
displayed alongside the basic *add new management profile* form. When
the form is processed, a new :py:class:`ManagementProfile` instance is
stored in the database, and each string in
``Meta.configuration_fields`` will be a key in the
``ManagementProfile.configuration`` dict, with values extracted from
the django form fields with corresponding names.
