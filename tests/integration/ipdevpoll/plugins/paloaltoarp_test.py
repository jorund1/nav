from django.urls import reverse
from nav.models.manage import ManagementProfile
from nav.ipdevpoll.plugins.paloaltoarp import PaloaltoArp

def test_netbox_with_paloalto_management_profile_should_get_arp_mappings(
        localhost, management_profile, db, client
):
    netbox_url = reverse('seeddb-netbox-edit', args=(localhost.id,))
    management_profile_url = reverse(
        'seeddb-management-profile-edit', args=(management_profile.id,)
    )

    # Manually sending this post request helps reveal regression bugs in case HTTPRestForm.service.choices keys are altered
    # since the post's invalid service field should then cause the form cleaning stage to fail. Changing the HTTPRestForm.choice
    # map to use enums as keys instead of strings would enable static analysis to reveal this.
    client.post(
        management_profile_url,
        follow=True,
        data={
            "name": management_profile.name,
            "description": management_profile.description,
            "protocol": ManagementProfile.PROTOCOL_HTTP_REST,
            "service": "Palo Alto ARP",
            "api_key": "1234",
        }
    )

    client.post(
        netbox_url,
        follow=True,
        data={
            "ip": localhost.ip,
            "room": localhost.room_id,
            "category": localhost.category_id,
            "organization": localhost.organization_id,
            "profiles": [management_profile.id],
        },
    )

    
  
  
 
