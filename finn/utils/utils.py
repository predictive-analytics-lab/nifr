import os
import math
from numbers import Number
import torch.nn.functional as F
import torch.distributions as td
import logging
import torch


LOGGER = None


def to_discrete(inputs, dim=1):
    if inputs.dim() <= 1 or inputs.size(1) <= 1:
        return inputs.round()
    else:
        argmax = inputs.argmax(dim=1)
        return F.one_hot(argmax, num_classes=inputs.size(1))


class RoundSTE(torch.autograd.Function):

    @staticmethod
    def forward(ctx, inputs):
        return inputs.round()

    @staticmethod
    def backward(ctx, grad_output):
        """Straight-through estimator
        """
        return grad_output


class BraceString(str):
    def __mod__(self, other):
        return self.format(*other)

    def __str__(self):
        return self


class StyleAdapter(logging.LoggerAdapter):
    def __init__(self, logger, extra=None):
        super(StyleAdapter, self).__init__(logger, extra)

    def process(self, msg, kwargs):
        # if kwargs.pop('style', "%") == "{":  # optional
        msg = BraceString(msg)
        return msg, kwargs


def get_logger(logpath, filepath, package_files=None, displaying=True, saving=True, debug=False):
    global LOGGER
    if LOGGER is not None:
        return LOGGER
    package_files = package_files or []

    logger = logging.getLogger()
    if debug:
        level = logging.DEBUG
    else:
        level = logging.INFO
    logger.setLevel(level)
    if saving:
        info_file_handler = logging.FileHandler(logpath, mode="a")
        info_file_handler.setLevel(level)
        logger.addHandler(info_file_handler)
    if displaying:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        logger.addHandler(console_handler)
    logger.info(filepath)
    # with open(filepath, "r") as f:
    #     logger.info(f.read())

    # for f in package_files:
    #     logger.info(f)
    #     with open(f, "r") as package_f:
    #         logger.info(package_f.read())

    LOGGER = StyleAdapter(logger)
    return LOGGER


class AverageMeter:
    """Computes and stores the average and current value"""

    def __init__(self):
        self.reset()

    def reset(self):
        self.val = 0
        self.avg = 0
        self.sum = 0
        self.count = 0

    def update(self, val, n=1):
        self.val = val
        self.sum += val * n
        self.count += n
        self.avg = self.sum / self.count


class RunningAverageMeter:
    """Computes and stores the average and current value"""

    def __init__(self, momentum=0.99):
        self.momentum = momentum
        self.reset()

    def reset(self):
        self.val = None
        self.avg = 0

    def update(self, val):
        if self.val is None:
            self.avg = val
        else:
            self.avg = self.avg * self.momentum + val * (1 - self.momentum)
        self.val = val


def inf_generator(iterable):
    """Allows training with DataLoaders in a single infinite loop:
        for i, (x, y) in enumerate(inf_generator(train_loader)):
    """
    iterator = iterable.__iter__()
    while True:
        try:
            yield iterator.__next__()
        except StopIteration:
            iterator = iterable.__iter__()


def save_checkpoint(state, save, epoch):
    if not os.path.exists(save):
        os.makedirs(save)
    filename = os.path.join(save, 'checkpt-%04d.pth' % epoch)
    torch.save(state, filename)


def isnan(tensor):
    return tensor != tensor


def standard_normal_logprob(z):
    """Log probability with respect to a normal distribution"""
    log_z = -0.5 * math.log(2 * math.pi)
    return log_z - z.pow(2) / 2


def count_parameters(model):
    """Count all parameters (that have a gradient) in the given model"""
    return sum(p.numel() for p in model.parameters() if p.requires_grad)
