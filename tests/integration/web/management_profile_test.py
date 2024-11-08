import pytest
import pytest_twisted
from django.urls import reverse

from nav.ipdevpoll.plugins.paloaltoarp import PaloaltoArp
from nav.models.manage import ManagementProfile, Netbox
from nav.web.seeddb.page.management_profile.forms import HttpApiForm


class TestHttpApiForm:
    class TestServiceChoices:
        """
        The HttpApiForm Django form, which creates HTTP API management profiles,
        stores a "service" key in the profile's configuration, used by other
        parts of NAV to differentiate between HTTP services:

        profile.configuration == {"service": "foo", ...}

        The HttpApiForm follows the convention of other management profile forms
        in not using named constants for ChoiceField values stored in the
        configuration dict. To help make sure that other parts of NAV use the
        same service values as those set by the form, we add tests below for
        each service choice.

        The tests first associates a service with a netbox through using the
        form, thus asserting that the service is a valid choice. Then it checks
        that the other parts of NAV accepts same service value as the one the
        form accepted.
        """

        tested_services = ["Palo Alto ARP"]

        @pytest.mark.twisted
        @pytest_twisted.inlineCallbacks
        def test_paloalto_plugin_should_use_the_service_choice_used_in_form(
            self, localhost, send_add_management_profile_form
        ):
            can_handle = yield PaloaltoArp.can_handle(localhost)
            assert not can_handle

            # Check that "Palo Alto ARP" is accepted by the form
            send_add_management_profile_form(
                localhost,
                protocol=ManagementProfile.PROTOCOL_HTTP_API,
                service="Palo Alto ARP",
                api_key="foo",
            )

            # Check that "Palo Alto ARP" is accepted by the plugin
            can_handle = yield PaloaltoArp.can_handle(localhost)
            assert can_handle

        def test_all_service_choices_should_have_a_test(self):
            all_services = (
                choice[0] for choice in HttpApiForm.declared_fields["service"].choices
            )
            missing_tests = set(all_services) - set(self.tested_services)
            error_message = (
                "If you've added a service choice to HttpApiForm, please add an "
                "integration test that checks that the service is correctly referenced "
                f"in other parts of NAV (missing tests for {', '.join(missing_tests)})"
            )
            assert not missing_tests, error_message


@pytest.fixture
def send_add_management_profile_form(client):
    """
    Example usage of this fixture:

    send_add_management_profile_form(netbox, ManagementProfile.PROTOCOL_DEBUG, foo="bar")

    This adds a management profile with protocol PROTOCOL_DEBUG and
    configuration={"foo": "bar"} to the given netbox by using the seeddb web
    form.
    """
    created_profiles = []

    def func(netbox: Netbox, protocol: int, **kwargs):
        profile = ManagementProfile(
            name="Test Profile",
            protocol=protocol,
            configuration={},
        )
        profile.save()
        created_profiles.append(profile)

        netbox_url = reverse("seeddb-netbox-edit", args=(netbox.id,))
        management_profile_url = reverse(
            "seeddb-management-profile-edit", args=(profile.id,)
        )

        client.post(
            management_profile_url,
            follow=True,
            data={
                "name": profile.name,
                "description": "",
                "protocol": protocol,
                **kwargs,
            },
        )
        client.post(
            netbox_url,
            follow=True,
            data={
                "ip": netbox.ip,
                "room": netbox.room_id,
                "category": netbox.category_id,
                "organization": netbox.organization_id,
                "profiles": [profile.id],
            },
        )
        profile.refresh_from_db()
        netbox.refresh_from_db()

    yield func
    for profile in created_profiles:
        profile.delete()
