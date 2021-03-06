"""
Plugin which tries to detect NSFW image URLs.

Requirements:

* Pillow
* requests
* jpeg decoder for PIL (libjpeg-dev package on Ubuntu)
"""

import os
import uuid
import tempfile
import regex
from os.path import join as pjoin

import requests
from PIL import Image

from base import BotPlugin

__all__ = (
    'NSFWImageDetectorPlugin'
)

IMAGE_EXTENSIONS = [
    '.png',
    '.jpg',
    '.gif'
]

CHUNK_SIZE = 1024

SKIN_PERCENTAGE_THRESHOLD = 30


class NSFWImageDetectorPlugin(BotPlugin):

    name = 'NSFW Image Detector'
    description = ('Scans image URLs for potential NSFW images and warns '
                   'users about them')

    def __init__(self, bot):
        super(NSFWImageDetectorPlugin, self).__init__(bot=bot)
        self._images_dir = tempfile.mkdtemp(suffix='nsfw-images')

    def handle_message(self, channel, nick, msg, line=None):
        urls = regex.WEB_URL.findall(msg)

        if not urls:
            return

        image_urls = self._get_image_urls(urls)

        if not image_urls:
            return

        nsfw_image_urls = self._process_images(urls=image_urls)

        for url in nsfw_image_urls:
            from response import NSFW_LINKS, random_response
            msg = random_response(NSFW_LINKS) % {'url': url, 'nick': nick}
            self.bot.say(msg, channel)

    def _process_images(self, urls):
        """
        Download all the images and return links which include potentially NSFW
        content.
        """
        nsfw_urls = []

        for url in urls:
            file_path = self._download_image(url=url)

            if file_path and os.path.isfile(file_path):
                try:
                    is_nsfw = self._is_nsfw_image(file_path=file_path)

                    if is_nsfw:
                        nsfw_urls.append(url)
                finally:
                    os.remove(file_path)

        return nsfw_urls

    def _is_nsfw_image(self, file_path):
        """
        Detect if the provided image file is NSFW.

        Current version of this function is very simple and only detects very
        basic nudity by measuring skin tone percentage in the image.
        """
        skin_percent = self._get_skin_ratio_percentage(file_path)
        return skin_percent > SKIN_PERCENTAGE_THRESHOLD

    def _get_skin_ratio_percentage(self, file_path):
        try:
            im = Image.open(file_path)
        except Exception:
            self.bot.log_error('Could not open NSFW image: "'
                               + file_path + '"')
            return 0.0

        im = im.convert('RGB')

        im = im.crop((int(im.size[0] * 0.2), int(im.size[1] * 0.2),
                      im.size[0] - int(im.size[0] * 0.2),
                      im.size[1] - int(im.size[1] * 0.2)))

        colors = im.getcolors(im.size[0] * im.size[1])

        skin = sum([count for count, rgb in colors if rgb[0] > 60
                    and rgb[1] < (rgb[0] * 0.85) and rgb[1] < (rgb[0] * 0.7)
                    and rgb[1] > (rgb[0] * 0.4) and rgb[1] > (rgb[0] * 0.2)])

        percentage = float(skin) / float(im.size[0] * im.size[1])
        percentage = percentage * 100
        return percentage

    def _get_image_urls(self, urls):
        """
        Filter urls to returns only image urls.

        Contains url transformers for a few common image sharers.
        """
        if not urls:
            return

        image_urls = []
        for url in urls:
            # Rewrite imgur urls
            imgur_res = regex.IMGUR.search(url)
            if imgur_res:
                url = "https://i.imgur.com/" + imgur_res.group('id') + ".jpg"

            if self._is_image_url(url=url):
                image_urls.append(url)

        return image_urls

    @staticmethod
    def _is_image_url(url):
        # Very simple logic, doesn't support urls which don't have an extension
        url = url.lower()
        extension = os.path.splitext(url)[1]

        return extension in IMAGE_EXTENSIONS

    def _download_image(self, url):
        """Download image in a temporary directory and return its path."""
        try:
            extension = os.path.splitext(url)[1]
            response = requests.get(url, stream=True)
        except Exception:
            self.bot.log_error('Failed to download NSFW image: "'
                               + url + '"')
            return

        if not response.status_code == 200:
            return

        name = str(uuid.uuid4()) + extension
        file_path = pjoin(self._images_dir, name)

        first_chunk = True
        with open(file_path, 'wb') as fp:
            for chunk in response.iter_content(CHUNK_SIZE):
                if first_chunk:
                    first_chunk = False
                    if not self._is_image(chunk):
                        self.bot.log_error('NSFW image was not an image: "'
                                           + url + '"')
                        return

                fp.write(chunk)

        return file_path

    # From http://people.iola.dk/olau/python/imagedetect.py by Ole Laursen
    @staticmethod
    def _is_jpg(data):
        """Return True if data is the first 2 bytes of a JPEG file."""
        return data[:2] == '\xff\xd8'

    @staticmethod
    def _is_png(data):
        """Return True if data is the first 8 bytes of a PNG file."""
        return data[:8] == '\x89PNG\x0d\x0a\x1a\x0a'

    @staticmethod
    def _is_gif(data):
        """Return True if data is the first 4 bytes of a GIF file."""
        return data[:4] == 'GIF8'

    def _is_image(self, data):
        """Return True if data conforms to a magic number of an image file."""
        return self._is_jpg(data) or self._is_png(data) or self._is_gif(data)
