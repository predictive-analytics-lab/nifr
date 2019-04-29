import torch.nn as nn

from layers.coupling import InvertibleLayer
from utils.utils import unsubslice, subslice


class SubsliceLayer(InvertibleLayer):

    def __init__(self):
        super(SubsliceLayer, self).__init__()

    def _forward(self, x, logpx):
        subslice_x = subslice(x)
        if logpx is None:
            return subslice_x
        else:
            return subslice_x, logpx

    def _reverse(self, x, logpx):
        unsubslice_x = unsubslice(x)
        if logpx is None:
            return unsubslice_x
        else:
            return unsubslice, logpx


class UnsubsliceLayer(InvertibleLayer):

    def __init__(self):
        super(UnsubsliceLayer, self).__init__()

    def _forward(self, x, logpx):
        subslice_x = unsubslice(x)
        if logpx is None:
            return subslice_x
        else:
            return subslice_x, logpx

    def _reverse(self, x, logpx):
        unsubslice_x = subslice(x)
        if logpx is None:
            return unsubslice_x
        else:
            return unsubslice, logpx



class SqueezeLayer(nn.Module):
    def __init__(self, downscale_factor):
        super(SqueezeLayer, self).__init__()
        self.downscale_factor = downscale_factor

    def forward(self, x, logpx=None, reverse=False):
        if reverse:
            return self._upsample(x, logpx)
        else:
            return self._downsample(x, logpx)

    def _downsample(self, x, logpx=None):
        squeeze_x = squeeze(x, self.downscale_factor)
        if logpx is None:
            return squeeze_x
        else:
            return squeeze_x, logpx

    def _upsample(self, y, logpy=None):
        unsqueeze_y = unsqueeze(y, self.downscale_factor)
        if logpy is None:
            return unsqueeze_y
        else:
            return unsqueeze_y, logpy


class UnsqueezeLayer(SqueezeLayer):

    def __init__(self, upscale_factor):
        super(UnsqueezeLayer, self).__init__(upscale_factor)

    def forward(self, x, logpx=None, reverse=False):
        if reverse:
            return self._downsample(x, logpx)
        else:
            return self._upsample(x, logpx)


def unsqueeze(input, upscale_factor=2):
    '''
    [:, C*r^2, H, W] -> [:, C, H*r, W*r]
    '''
    batch_size, in_channels, in_height, in_width = input.size()
    out_channels = in_channels // (upscale_factor**2)

    out_height = in_height * upscale_factor
    out_width = in_width * upscale_factor

    input_view = input.contiguous().view(batch_size, out_channels, upscale_factor, upscale_factor, in_height, in_width)

    output = input_view.permute(0, 1, 4, 2, 5, 3).contiguous()
    return output.view(batch_size, out_channels, out_height, out_width)


def squeeze(input, downscale_factor=2):
    '''
    [:, C, H*r, W*r] -> [:, C*r^2, H, W]
    '''
    batch_size, in_channels, in_height, in_width = input.size()
    out_channels = in_channels * (downscale_factor**2)

    out_height = in_height // downscale_factor
    out_width = in_width // downscale_factor

    input_view = input.contiguous().view(
        batch_size, in_channels, out_height, downscale_factor, out_width, downscale_factor
    )

    output = input_view.permute(0, 1, 3, 5, 2, 4).contiguous()
    return output.view(batch_size, out_channels, out_height, out_width)
