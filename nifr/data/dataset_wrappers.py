import random
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Tuple

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader, Dataset, Subset
from torchvision import transforms

from .misc import RandomSampler, grouped_features_indexes, set_transform


class LdAugmentedDataset(Dataset):
    def __init__(
        self,
        source_dataset,
        ld_augmentations,
        num_classes,
        li_augmentation=False,
        base_augmentations: Optional[List] = None,
        correlation=1.0,
    ):

        self.source_dataset = self._validate_dataset(source_dataset)
        if not 0 <= correlation <= 1:
            raise ValueError("Label-augmentation correlation must be between 0 and 1.")

        self.num_classes = num_classes

        if not isinstance(ld_augmentations, (list, tuple)):
            ld_augmentations = [ld_augmentations]
        self.ld_augmentations = ld_augmentations

        if base_augmentations is not None:
            base_augmentations = transforms.Compose(base_augmentations)
            set_transform(self.source_dataset, base_augmentations)
        self.base_augmentations = base_augmentations

        self.li_augmentation = li_augmentation
        self.correlation = correlation

        self.dataset = self._validate_dataset(source_dataset)

    def __len__(self):
        return len(self.dataset)

    @staticmethod
    def _validate_dataset(dataset):
        if isinstance(dataset, DataLoader):
            dataset = dataset
        elif not isinstance(dataset, Dataset):
            raise TypeError("Dataset must be a Dataset or Dataloader object.")

        return dataset

    def subsample(self, pcnt=1.0):
        if not 0 <= pcnt <= 1.0:
            raise ValueError(f"{pcnt} should be in the range (0, 1]")
        num_samples = int(pcnt * len(self.source_dataset))
        inds = list(RandomSampler(self.source_dataset, num_samples=num_samples, replacement=False))
        self.inds = inds
        subset = self._sample_from_inds(inds)
        self.dataset = subset

    def _sample_from_inds(self, inds):
        subset = Subset(self.source_dataset, inds)

        return subset

    @staticmethod
    def _validate_data(*args):
        for arg in args:
            if not isinstance(arg, torch.Tensor):
                dtype = torch.long if type(arg) == int else torch.float32
                arg = torch.tensor(arg, dtype=dtype)
            if arg.dim() == 0:
                arg = arg.view(-1)
            yield (arg)

    def __getitem__(self, index):
        return self._subroutine(self.dataset.__getitem__(index))

    def _augment(self, x, label):
        for aug in self.ld_augmentations:
            x = aug(x, label)

        return x

    def _subroutine(self, data):

        x, y = data
        s = y
        x, s, y = self._validate_data(x, s, y)

        if self.li_augmentation:
            s = torch.randint_like(s, low=0, high=self.num_classes)

        if self.correlation < 1:
            flip_prob = torch.rand(s.shape)
            indexes = flip_prob > self.correlation
            s[indexes] = s[indexes][torch.randperm(indexes.size(0))]

        x = self._augment(x, s)

        if x.dim() == 4 and x.size(1) == 1:
            x = x.repeat(1, 3, 1, 1)
        x = x.squeeze(0)
        s = s.squeeze()
        y = y.squeeze()

        return x, s, y


if TYPE_CHECKING:
    BaseDataset = Dataset[Tuple[torch.Tensor, torch.Tensor, torch.Tensor]]
else:
    BaseDataset = Dataset


class DataTupleDataset(BaseDataset):
    """Wrapper for EthicML datasets"""

    def __init__(self, dataset, disc_features: List[str], cont_features: List[str], transform=None):

        disc_features = [feat for feat in disc_features if feat in dataset.x.columns]
        self.disc_features = disc_features

        cont_features = [feat for feat in cont_features if feat in dataset.x.columns]
        self.cont_features = cont_features
        self.feature_groups = dict(discrete=grouped_features_indexes(self.disc_features))

        self.x_disc = dataset.x[self.disc_features].to_numpy(dtype=np.float32)
        self.x_cont = dataset.x[self.cont_features].to_numpy(dtype=np.float32)
        self.s = dataset.s.to_numpy(dtype=np.float32)
        self.y = dataset.y.to_numpy(dtype=np.float32)

        self.transform = transform

    def __len__(self):
        return self.s.shape[0]

    def shrink(self, pcnt):
        if not 0.0 <= pcnt <= 1.0:
            raise ValueError(f"{pcnt} is not a valid percentage")
        new_len = round(pcnt * self.__len__())
        inds = random.sample(range(self.__len__()), new_len)
        self.x_disc = self.x_disc[inds]
        self.x_cont = self.x_cont[inds]
        self.s = self.s[inds]
        self.y = self.y[inds]

    @property
    def transform(self):
        return self.__transform

    @transform.setter
    def transform(self, t):
        t = t or []
        if not isinstance(t, list):
            t = [t]
        self.__transform = t

    def __getitem__(self, index: int) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:

        x_disc = self.x_disc[index]
        x_cont = self.x_cont[index]
        s = self.s[index]
        y = self.y[index]

        for tform in self.transform:
            if isinstance(tform, dict):
                if tform["disc"]:
                    x_disc = tform["disc"](x_disc, self.feature_groups)
                if tform["cont"]:
                    x_cont = tform["cont"](x_cont)
            else:
                x_cont = tform(x_cont)
                x_disc = tform(x_disc)

        x = np.concatenate([x_disc, x_cont], axis=0)
        x = torch.from_numpy(x).squeeze(0)
        s = torch.from_numpy(s).squeeze()
        y = torch.from_numpy(y).squeeze()

        return x, s, y


class PerturbedDataTupleDataset(DataTupleDataset):
    def __init__(self, dataset, features: List[str], num_bins: np.ndarray, transform=None):
        super().__init__(dataset, disc_features=[], cont_features=features, transform=transform)
        self.bin_size = 1 / num_bins
        self.random = np.random.RandomState(seed=42)

    def __getitem__(self, index):

        x = self.x_cont[index]
        s = self.s[index]
        y = self.y[index]

        # add a bit of noise
        x += self.random.uniform(low=0, high=self.bin_size, size=x.shape)

        x = torch.from_numpy(x).squeeze(0)
        s = torch.from_numpy(s).squeeze()
        y = torch.from_numpy(y).squeeze()

        return x, s, y


class TripletDataset(Dataset):
    def __init__(self, root: str):
        super().__init__()

        self.root_path = Path(root)

        def _abs(file_name: str) -> Path:
            return self.root_path / file_name

        filename = pd.read_csv(
            _abs("filename.csv"), delim_whitespace=True, header=None, index_col=0
        )
        sens = pd.read_csv(_abs("sens.csv"), delim_whitespace=True, header=None)
        target = pd.read_csv(_abs("target.csv"), delim_whitespace=True, header=None)

        assert filename.shape[0] == sens.shape[0] == target.shape[0]

        self.filename = filename.index.values
        self.sens = torch.as_tensor(sens.values)
        self.target = torch.as_tensor(target.values)

    def __len__(self):
        return self.target.size(0)

    def __getitem__(self, index):
        """
        Args:
            index (int): Index
        Returns:
            tuple: (image, target) where target is index of the target class.
        """
        img = np.load(self.root_path / self.filename[index])
        img = torch.as_tensor(img["img"])
        sens = self.sens[index]
        target = self.target[index]

        return img, sens, target
