from django.test import SimpleTestCase
from django.urls import reverse


class DashboardViewTests(SimpleTestCase):
    def test_dashboard_url_returns_200_ok(self):
        url = reverse('dispatch:dashboard')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'dispatch/dashboard.html')
        self.assertContains(response, 'Fleet Dispatch')
        self.assertContains(response, 'leaflet.js')