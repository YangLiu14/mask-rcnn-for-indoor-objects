import os
import sys
import numpy as np
import torch
import pickle

from PIL import Image
from torch.utils.data import Dataset

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)


object_dict = dict()

class ScannetDataset(Dataset):

    def __init__(self, root, transforms=None, data_split='all'):
        self.root = root
        self.transforms = transforms
        # load all image files, sorting them to
        # ensure that they are aligned
        self.imgs = list(sorted(os.listdir(os.path.join(root, data_split, "raw_rgb"))))
        self.masks = list(sorted(os.listdir(os.path.join(root, data_split, "label_mask"))))
        self.bboxs = list(sorted(os.listdir(os.path.join(root, data_split, "bbox"))))
        self.data_split = data_split

    def __getitem__(self, idx):
        # load images and masks
        img_path = os.path.join(self.root, self.data_split, "raw_rgb", self.imgs[idx])
        mask_path = os.path.join(self.root, self.data_split, "label_mask", self.masks[idx])
        img = Image.open(img_path).convert("RGB")
        mask = Image.open(mask_path)
        mask = np.array(mask)

        # obj_ids = np.unique(mask)
        # # first id is the background, so remove it
        # obj_ids = obj_ids[1:]

        # split the color-encoded mask into a set
        # of binary masks
        # masks = mask == obj_ids[:, None, None]

        # get bounding box coordinates for each mask
        # num_objs = len(obj_ids)
        boxes = []
        bbox_path = os.path.join(self.root, self.data_split, "bbox", self.bboxs[idx])
        bbox_dict_list = pickle.load(open(bbox_path, "rb"))

        obj_ids = []
        sem_labels = []
        for bbox_dict in bbox_dict_list:
            # Check: valid bounding-boxes should not have `xmin==xmax or ymin==ymax`
            bbox = bbox_dict['bbox']
            if not (bbox[0] == bbox[2] or bbox[1] == bbox[3]):
                boxes.append(bbox_dict['bbox'])
                sem_labels.append(bbox_dict['sem_label'])
                obj_ids.append(bbox_dict['object_id'] + 1)

            object_dict[bbox_dict['sem_label']] = bbox_dict['object_name']

        if boxes == []:
            Exception("Incomplete data: boxes list is empty!!")

        num_objs = len(obj_ids)
        obj_ids = np.array(obj_ids)
        masks = mask == obj_ids[:, None, None]

        # boxes_test = []
        # for i in range(num_objs):
        #     pos = np.where(masks[i])
        #     xmin = np.min(pos[1])
        #     xmax = np.max(pos[1])
        #     ymin = np.min(pos[0])
        #     ymax = np.max(pos[0])
        #     boxes_test.append([xmin, ymin, xmax, ymax])
        # boxes_test = torch.as_tensor(boxes_test, dtype=torch.float32)

        # convert everything into a torch.Tensor
        boxes = torch.as_tensor(boxes, dtype=torch.float32)
        labels = torch.as_tensor(sem_labels, dtype=torch.int64)
        masks = torch.as_tensor(masks, dtype=torch.uint8)

        image_id = torch.tensor([idx])
        try:
            area = (boxes[:, 3] - boxes[:, 1]) * (boxes[:, 2] - boxes[:, 0])
        except:
            print("asddsda")
        # suppose all instances are not crowd
        # instances with `iscrowd=True` will be ignored during evaluation.
        iscrowd = torch.zeros((num_objs,), dtype=torch.int64)

        target = {}
        target["boxes"] = boxes
        target["labels"] = labels
        target["masks"] = masks
        target["image_id"] = image_id
        target["area"] = area
        target["iscrowd"] = iscrowd

        if self.transforms is not None:
            img, target = self.transforms(img, target)

        return img, target

    def __len__(self):
        return len(self.imgs)

if __name__ == "__main__":
    print("BASE_DIR")
    print(BASE_DIR)
    print("ROOT_DIR")
    print(ROOT_DIR)
    print("data_path")
    data_path = os.path.join(ROOT_DIR, 'data/maskrcnn_training')
    print(data_path)


    # test_dataset = ScannetDataset(data_path)
    # img, target = test_dataset.__getitem__(1)
    # img.show()
    # mask = target['masks'].numpy()
    # print(type(img))
    # print(target)

    # check how many classes are there
    classes = set()
    test_dataset = ScannetDataset(data_path, data_split='train')
    for i in range(433):
        img, target = test_dataset.__getitem__(i)
        labels = target['labels'].numpy()
        for label in labels:
            classes.add(label)
    print(classes)
    print(object_dict)
